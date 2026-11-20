# Copyright (C) 2026 CuckooIsland Contributors
# SPDX-License-Identifier: MIT
"""CuckooIsland - CuckooInterface 与 ClassIsland 的双向桥接插件。

职责：
1. 读取 ClassIsland 的课表配置，计算「当前科目 / 剩余时间 / 下一节」；
2. 把课程状态以事件形式发布到 CuckooInterface 事件总线；
3. 读取并修改 ClassIsland 的自动化配置；
4. 自动注入 ClassIsland 侧桥接插件，把事件以提醒形式显示在 ClassIsland 上；
5. 通过宿主配置存储与配置页双向交换设置、操作请求和运行状态。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PLUGIN_ID = "com.cuckoo.plugin.cuckoo_island"

DEFAULT_CONFIG: Dict[str, Any] = {
    "classisland_dir": "",
    "ui_commands": [],
    "ui_results": [],
    "runtime_state": {},
    "automation_state": {},
    "poll_seconds": 10,
    "emit_events": True,
    "notify_lesson_start": True,
    "notify_lesson_end": True,
    "notify_break": False,
    "auto_inject_bridge": True,
    "automation_file": "Default.json",
}

# ---------------------------------------------------------------------------
# SDK（脱离宿主时降级为空实现，便于本地调试）
# ---------------------------------------------------------------------------

try:
    from cuckoo_sdk import (  # type: ignore
        emit_event as _sdk_emit,
        get_plugin_config as _sdk_get_config,
        log_error as _sdk_log_error,
        log_info as _sdk_log_info,
        set_plugin_config as _sdk_set_config,
    )

    HAS_SDK = True
except Exception:  # pragma: no cover - 本地独立运行
    HAS_SDK = False

    def _sdk_emit(event_name: str, payload: Any = None) -> None:
        return None

    def _sdk_get_config(plugin_name: str) -> Dict[str, Any]:
        return {}

    def _sdk_set_config(plugin_name: str, config: Any) -> None:
        return None

    def _sdk_log_info(msg: str) -> None:
        print(f"[info] {msg}")

    def _sdk_log_error(msg: str) -> None:
        print(f"[error] {msg}")


def log_info(msg: str) -> None:
    try:
        _sdk_log_info(f"[CuckooIsland] {msg}")
    except Exception:
        pass


def log_error(msg: str) -> None:
    try:
        _sdk_log_error(f"[CuckooIsland] {msg}")
    except Exception:
        pass


def emit_event(name: str, payload: Any = None) -> None:
    try:
        _sdk_emit(name, payload)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8-sig") as fp:
        return json.load(fp)


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def parse_hhmmss(value: str) -> Optional[int]:
    """把 "08:00:00" 解析成当天秒数。"""
    if not value:
        return None
    parts = value.strip().split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return None
    return hour * 3600 + minute * 60 + second


def seconds_to_text(total: int) -> str:
    total = max(0, int(total))
    hour, rem = divmod(total, 3600)
    minute, second = divmod(rem, 60)
    if hour:
        return f"{hour} 小时 {minute} 分"
    if minute:
        return f"{minute} 分 {second} 秒"
    return f"{second} 秒"


# ---------------------------------------------------------------------------
# ClassIsland 定位
# ---------------------------------------------------------------------------

_COMMON_DIRS = [
    r"%LOCALAPPDATA%\ClassIsland",
    r"%APPDATA%\ClassIsland",
    r"%ProgramFiles%\ClassIsland",
    r"%ProgramFiles(x86)%\ClassIsland",
    r"D:\ClassIsland",
    r"C:\ClassIsland",
]


def _is_classisland_dir(path: Path) -> bool:
    try:
        return (path / "data" / "Settings.json").is_file()
    except OSError:
        return False


def _parse_registry_command(command: str) -> Optional[Path]:
    command = command.strip()
    if not command:
        return None
    if command.startswith('"'):
        end = command.find('"', 1)
        if end > 1:
            exe = command[1:end]
            return Path(exe).parent
    else:
        exe = command.split(" ")[0]
        if exe.lower().endswith(".exe"):
            return Path(exe).parent
    return None


def _dirs_from_registry() -> List[Path]:
    result: List[Path] = []
    if os.name != "nt":
        return result
    try:
        import winreg  # type: ignore
    except Exception:
        return result

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, getattr(winreg, "KEY_WOW64_64KEY", 0)):
            try:
                with winreg.OpenKey(
                    hive,
                    r"Software\Classes\classisland\shell\open\command",
                    0,
                    winreg.KEY_READ | view,
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "")
                    parsed = _parse_registry_command(value)
                    if parsed:
                        result.append(parsed)
            except OSError:
                continue
    return result


def _dirs_from_process() -> List[Path]:
    """用 Toolhelp 快照找到正在运行的 ClassIsland.exe 路径，避免依赖 wmic。"""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == wintypes.HANDLE(-1).value:
            return []

        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        found: List[Path] = []
        try:
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.szExeFile.lower() == "classisland.exe":
                    handle = kernel32.OpenProcess(
                        PROCESS_QUERY_LIMITED_INFORMATION, False, entry.th32ProcessID
                    )
                    if handle:
                        try:
                            size = wintypes.DWORD(1024)
                            buffer = ctypes.create_unicode_buffer(size.value)
                            if kernel32.QueryFullProcessImageNameW(
                                handle, 0, buffer, ctypes.byref(size)
                            ):
                                found.append(Path(buffer.value).parent)
                        finally:
                            kernel32.CloseHandle(handle)
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return found
    except Exception:
        return []


def _dirs_from_uninstall() -> List[Path]:
    """从卸载表里找 ClassIsland 的安装目录，补上注册表协议过期的情况。"""
    result: List[Path] = []
    if os.name != "nt":
        return result
    try:
        import winreg  # type: ignore
    except Exception:
        return result

    roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, root in roots:
        try:
            with winreg.OpenKey(hive, root) as key:
                count = winreg.QueryInfoKey(key)[0]
        except OSError:
            continue
        for index in range(count):
            try:
                sub_name = winreg.EnumKey(key, index)
                with winreg.OpenKey(key, sub_name) as sub:
                    display = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                    if "classisland" not in display.lower():
                        continue
                    for value_name in ("InstallLocation", "DisplayIcon"):
                        try:
                            raw = str(winreg.QueryValueEx(sub, value_name)[0])
                        except OSError:
                            continue
                        raw = raw.strip().strip('"')
                        if not raw:
                            continue
                        path = Path(raw.split(",")[0])
                        result.append(path if path.is_dir() else path.parent)
            except OSError:
                continue
    return result


def discover_classisland(configured: str) -> Tuple[Optional[Path], str]:
    """返回 (安装目录, 来源说明)。"""
    candidates: List[Tuple[Path, str]] = []

    if configured and configured.strip():
        candidates.append((Path(configured.strip()), "配置"))

    for path in _dirs_from_registry():
        candidates.append((path, "注册表"))

    for path in _dirs_from_uninstall():
        candidates.append((path, "卸载表"))

    for path in _dirs_from_process():
        candidates.append((path, "运行中的进程"))

    for raw in _COMMON_DIRS:
        expanded = os.path.expandvars(raw)
        if "%" not in expanded:
            candidates.append((Path(expanded), "默认路径"))

    for path, source in candidates:
        if _is_classisland_dir(path):
            return path, source
    return None, "未找到"


# ---------------------------------------------------------------------------
# 课表解析
# ---------------------------------------------------------------------------


class LessonState:
    """一次课表快照。"""

    def __init__(self) -> None:
        self.ok = False
        self.error = ""
        self.classisland_dir = ""
        self.profile_name = ""
        self.plan_name = ""
        self.plan_id = ""
        self.status = "unknown"  # class / break / idle
        self.subject = ""
        self.teacher = ""
        self.start_at = ""
        self.end_at = ""
        self.remaining_seconds = 0
        self.lesson_index = 0
        self.lesson_count = 0
        self.next_subject = ""
        self.next_start_at = ""
        self.break_name = ""
        self.updated_at = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "classislandDir": self.classisland_dir,
            "profile": self.profile_name,
            "plan": self.plan_name,
            "planId": self.plan_id,
            "status": self.status,
            "subject": self.subject,
            "teacher": self.teacher,
            "startAt": self.start_at,
            "endAt": self.end_at,
            "remainingSeconds": self.remaining_seconds,
            "remainingText": seconds_to_text(self.remaining_seconds),
            "lessonIndex": self.lesson_index,
            "lessonCount": self.lesson_count,
            "nextSubject": self.next_subject,
            "nextStartAt": self.next_start_at,
            "breakName": self.break_name,
            "updatedAt": self.updated_at,
        }


def _select_class_plan(profile: Dict[str, Any], today: date, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    plans = profile.get("ClassPlans") or {}
    if not isinstance(plans, dict):
        return None

    # ClassIsland 的 WeekDay：0 = 周日，1 = 周一 …… 6 = 周六
    weekday = (today.weekday() + 1) % 7

    week_div = 0
    try:
        start_text = str(settings.get("SingleWeekStartTime") or "")
        if start_text:
            start_date = datetime.fromisoformat(start_text).date()
            week_number = (today - start_date).days // 7 + 1
            week_div = 1 if week_number % 2 == 1 else 2
    except Exception:
        week_div = 0

    selected_group = profile.get("SelectedClassPlanGroupId")
    best: Optional[Dict[str, Any]] = None

    for plan_id, plan in plans.items():
        if not isinstance(plan, dict) or not plan.get("IsEnabled", True):
            continue
        if plan.get("IsOverlay"):
            continue
        rule = plan.get("TimeRule") or {}
        try:
            if int(rule.get("WeekDay", -1)) != weekday:
                continue
            div = int(rule.get("WeekCountDiv", 0) or 0)
        except (TypeError, ValueError):
            continue
        if div not in (0, week_div):
            continue

        candidate = dict(plan)
        candidate["_id"] = plan_id
        if selected_group and plan.get("AssociatedGroup") == selected_group:
            return candidate
        if best is None:
            best = candidate
    return best


def compute_state(ci_dir: Optional[Path], now: Optional[datetime] = None) -> LessonState:
    state = LessonState()
    now = now or datetime.now()
    state.updated_at = now.strftime("%Y-%m-%d %H:%M:%S")

    if ci_dir is None:
        state.error = "未找到 ClassIsland，请在插件配置中指定安装目录。"
        return state

    state.classisland_dir = str(ci_dir)
    data_dir = ci_dir / "data"
    settings_path = data_dir / "Settings.json"

    try:
        settings = read_json(settings_path)
    except Exception as exc:
        state.error = f"读取 Settings.json 失败：{exc}"
        return state

    profile_name = str(settings.get("SelectedProfile") or "Default.json")
    state.profile_name = profile_name

    try:
        profile = read_json(data_dir / "Profiles" / profile_name)
    except Exception as exc:
        state.error = f"读取课表 {profile_name} 失败：{exc}"
        return state

    plan = _select_class_plan(profile, now.date(), settings)
    if not plan:
        state.error = "今天没有匹配的课表（可能未启用或周次不匹配）。"
        state.ok = True
        state.status = "idle"
        return state

    state.plan_name = str(plan.get("Name") or "")
    state.plan_id = str(plan.get("_id") or "")

    layouts = profile.get("TimeLayouts") or {}
    layout = layouts.get(plan.get("TimeLayoutId"))
    if not isinstance(layout, dict):
        state.error = "课表没有关联有效的时间表。"
        state.ok = True
        state.status = "idle"
        return state

    subjects = profile.get("Subjects") or {}
    classes = plan.get("Classes") or []

    items = [item for item in (layout.get("Layouts") or []) if isinstance(item, dict)]
    items.sort(key=lambda item: parse_hhmmss(str(item.get("StartTime") or "")) or 0)

    now_seconds = now.hour * 3600 + now.minute * 60 + now.second
    class_items: List[Dict[str, Any]] = []
    for item in items:
        if int(item.get("TimeType", 0) or 0) == 0:
            class_items.append(item)

    state.lesson_count = len(classes) or len(class_items)

    current_class_index = -1
    current_item: Optional[Dict[str, Any]] = None
    next_subject = ""
    next_start = ""

    for index, item in enumerate(class_items):
        start = parse_hhmmss(str(item.get("StartTime") or ""))
        end = parse_hhmmss(str(item.get("EndTime") or ""))
        if start is None or end is None:
            continue
        if start <= now_seconds < end:
            current_class_index = index
            current_item = item
            break

    # 判断是否处于课间
    if current_item is None:
        for item in items:
            start = parse_hhmmss(str(item.get("StartTime") or ""))
            end = parse_hhmmss(str(item.get("EndTime") or ""))
            if start is None or end is None:
                continue
            if start <= now_seconds < end:
                state.status = "break"
                state.break_name = str(item.get("BreakName") or "课间")
                state.start_at = str(item.get("StartTime") or "")
                state.end_at = str(item.get("EndTime") or "")
                state.remaining_seconds = end - now_seconds
                break

    def subject_name(class_index: int) -> Tuple[str, str]:
        if class_index < 0 or class_index >= len(classes):
            return "", ""
        subject_id = (classes[class_index] or {}).get("SubjectId")
        subject = subjects.get(subject_id) or {}
        return str(subject.get("Name") or ""), str(subject.get("TeacherName") or "")

    if current_item is not None:
        start = parse_hhmmss(str(current_item.get("StartTime") or "")) or now_seconds
        end = parse_hhmmss(str(current_item.get("EndTime") or "")) or now_seconds
        state.status = "class"
        state.subject, state.teacher = subject_name(current_class_index)
        state.start_at = str(current_item.get("StartTime") or "")
        state.end_at = str(current_item.get("EndTime") or "")
        state.remaining_seconds = max(0, end - now_seconds)
        state.lesson_index = current_class_index + 1

    # 下一节
    start_index = current_class_index + 1 if current_class_index >= 0 else 0
    for index in range(start_index, len(class_items)):
        item = class_items[index]
        start = parse_hhmmss(str(item.get("StartTime") or ""))
        if start is None or start <= now_seconds:
            continue
        name, _ = subject_name(index)
        if name:
            next_subject = name
            next_start = str(item.get("StartTime") or "")
            break

    if state.status != "break" and current_item is None:
        state.status = "idle"

    state.next_subject = next_subject
    state.next_start_at = next_start
    state.ok = True
    return state


# ---------------------------------------------------------------------------
# 自动化配置
# ---------------------------------------------------------------------------

NOTIFICATION_ACTION_TEMPLATE = {
    "IsCompleted": True,
    "Id": "classisland.showNotification",
    "Settings": {
        "Content": "",
        "Mask": "",
        "IsContentSpeechEnabled": False,
        "IsMaskSpeechEnabled": False,
        "IsAdvancedSettingsEnabled": False,
        "IsSoundEffectEnabled": True,
        "IsTopmostEnabled": True,
        "CustomSoundEffectPath": "",
        "IsEffectEnabled": True,
        "MaskDurationSeconds": 6,
        "ContentDurationSeconds": 10,
        "IsWaitForCompleteEnabled": False,
        "IsActive": False,
    },
    "IsActive": False,
}


class AutomationStore:
    def __init__(self, ci_dir: Optional[Path], file_name: str) -> None:
        self.ci_dir = ci_dir
        self._file_name = "Default.json"
        self.file_name = file_name or "Default.json"

    @property
    def file_name(self) -> str:
        return self._file_name

    @file_name.setter
    def file_name(self, value: str) -> None:
        name = str(value or "").strip()
        if (
            not name
            or name in (".", "..")
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or not name.lower().endswith(".json")
        ):
            raise ValueError("自动化文件名必须是单层 .json 文件名")
        self._file_name = name

    @property
    def dir(self) -> Optional[Path]:
        if self.ci_dir is None:
            return None
        return self.ci_dir / "data" / "Config" / "Automations"

    @property
    def path(self) -> Optional[Path]:
        directory = self.dir
        if directory is None:
            return None
        root = directory.resolve()
        candidate = (root / self.file_name).resolve()
        # resolve() 同时处理 ..、绝对路径和指向目录外的符号链接。
        if candidate.parent != root or candidate.suffix.lower() != ".json":
            raise ValueError("自动化文件路径超出 Automations 目录")
        return candidate

    def list_files(self) -> List[str]:
        directory = self.dir
        if directory is None or not directory.is_dir():
            return []
        return sorted(p.name for p in directory.glob("*.json"))

    def load(self) -> Dict[str, Any]:
        path = self.path
        if path is None:
            return {"ok": False, "error": "未找到 ClassIsland", "items": [], "files": []}
        if not path.is_file():
            return {"ok": False, "error": f"自动化文件不存在：{self.file_name}", "items": [], "files": self.list_files()}

        try:
            items = read_json(path)
        except Exception as exc:
            return {"ok": False, "error": f"解析失败：{exc}", "items": [], "files": self.list_files()}

        if not isinstance(items, list):
            return {"ok": False, "error": "自动化文件格式不是数组", "items": [], "files": self.list_files()}

        summary = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                summary.append({"index": index, "name": f"#{index + 1}（格式异常）", "triggers": 0, "actions": 0})
                continue
            action_set = item.get("ActionSet") or {}
            actions = action_set.get("Actions") if isinstance(action_set, dict) else []
            triggers = item.get("Triggers") or []
            summary.append(
                {
                    "index": index,
                    "name": str(action_set.get("Name") or f"#{index + 1}") if isinstance(action_set, dict) else f"#{index + 1}",
                    "triggers": len(triggers) if isinstance(triggers, list) else 0,
                    "actions": len(actions) if isinstance(actions, list) else 0,
                    "triggerNames": [
                        str((t or {}).get("Id") or "") for t in (triggers if isinstance(triggers, list) else [])
                    ],
                }
            )

        return {
            "ok": True,
            "file": self.file_name,
            "files": self.list_files(),
            "items": summary,
            "raw": items,
            "path": str(path),
            "updatedAt": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }

    def save(self, items: Any) -> Dict[str, Any]:
        path = self.path
        if path is None:
            return {"ok": False, "error": "未找到 ClassIsland"}
        if not isinstance(items, list):
            return {"ok": False, "error": "内容必须是 JSON 数组"}

        try:
            backup = path.with_suffix(f".cuckoo-backup-{int(time.time())}.json")
            if path.is_file():
                shutil.copy2(path, backup)
            write_json_atomic(path, items)
            return {"ok": True, "backup": str(backup)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def insert_notification(self, index: int, title: str, message: str) -> Dict[str, Any]:
        loaded = self.load()
        if not loaded.get("ok"):
            return loaded
        items = loaded.get("raw") or []
        if index < 0 or index >= len(items):
            return {"ok": False, "error": "自动化序号超出范围"}

        item = items[index]
        if not isinstance(item, dict):
            return {"ok": False, "error": "目标自动化格式异常"}

        action_set = item.setdefault("ActionSet", {})
        if not isinstance(action_set, dict):
            return {"ok": False, "error": "ActionSet 格式异常"}
        actions = action_set.setdefault("Actions", [])
        if not isinstance(actions, list):
            return {"ok": False, "error": "Actions 格式异常"}

        action = json.loads(json.dumps(NOTIFICATION_ACTION_TEMPLATE))
        action["Settings"]["Content"] = message or title
        action["Settings"]["Mask"] = title or message
        actions.append(action)

        result = self.save(items)
        if result.get("ok"):
            result["action"] = action
        return result


# ---------------------------------------------------------------------------
# 桥接（通知队列 + 插件注入）
# ---------------------------------------------------------------------------

BRIDGE_PLUGIN_ID = "cuckoo.island.bridge"


class BridgeManager:
    def __init__(self, ci_dir: Optional[Path]) -> None:
        self.ci_dir = ci_dir
        self._lock = threading.Lock()

    def set_dir(self, ci_dir: Optional[Path]) -> None:
        self.ci_dir = ci_dir

    @property
    def plugin_dir(self) -> Optional[Path]:
        if self.ci_dir is None:
            return None
        return self.ci_dir / "data" / "Plugins" / BRIDGE_PLUGIN_ID

    @property
    def queue_path(self) -> Optional[Path]:
        directory = self.plugin_dir
        return None if directory is None else directory / "bridge" / "notifications.jsonl"

    def status(self) -> Dict[str, Any]:
        plugin_dir = self.plugin_dir
        queue = self.queue_path
        installed = bool(plugin_dir and (plugin_dir / "CuckooIslandBridge.dll").is_file())
        return {
            "installed": installed,
            "pluginDir": str(plugin_dir) if plugin_dir else "",
            "queue": str(queue) if queue else "",
            "queueExists": bool(queue and queue.is_file()),
            "queueSize": queue.stat().st_size if queue and queue.is_file() else 0,
            "version": self._installed_version(plugin_dir) if installed else "",
        }

    @staticmethod
    def _installed_version(plugin_dir: Optional[Path]) -> str:
        if plugin_dir is None:
            return ""
        manifest = plugin_dir / "manifest.yml"
        if not manifest.is_file():
            return ""
        for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("version:"):
                return line.split(":", 1)[1].strip()
        return ""

    def inject(self) -> Dict[str, Any]:
        """把插件自带的 ClassIsland 桥接插件复制到 ClassIsland 插件目录。"""
        if self.ci_dir is None:
            return {"ok": False, "error": "未找到 ClassIsland"}
        source = Path(__file__).resolve().parent / "island-bridge"
        if not source.is_dir():
            return {"ok": False, "error": "插件缺少 island-bridge 资源"}

        target = self.plugin_dir
        assert target is not None
        try:
            target.mkdir(parents=True, exist_ok=True)
            copied = []
            for item in source.iterdir():
                if item.is_file() and item.suffix.lower() in (".dll", ".yml", ".yaml", ".json"):
                    shutil.copy2(item, target / item.name)
                    copied.append(item.name)
            (target / "bridge").mkdir(parents=True, exist_ok=True)
            return {"ok": True, "target": str(target), "files": copied, "version": self._installed_version(target)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def push_notification(self, title: str, message: str = "", duration: float = 6.0) -> bool:
        queue = self.queue_path
        if queue is None:
            return False
        try:
            queue.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "id": f"{int(time.time() * 1000)}",
                "ts": int(time.time()),
                "title": title,
                "message": message,
                "duration": duration,
            }
            with self._lock:
                with open(queue, "a", encoding="utf-8", newline="\n") as fp:
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except Exception as exc:
            log_error(f"写入提醒队列失败：{exc}")
            return False


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------


class IslandService:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.ci_dir: Optional[Path] = None
        self.dir_source = ""
        self.bridge = BridgeManager(None)
        self.automation = AutomationStore(None, self.config["automation_file"])
        self.last_state: LessonState = LessonState()
        self.last_key: Optional[Tuple[Any, ...]] = None
        self.last_error = ""
        self.injected_version = ""
        self._discovery: Optional[Tuple[str, float]] = None

    # -- 配置 -----------------------------------------------------------
    def reload_config(self) -> None:
        raw = {}
        try:
            raw = _sdk_get_config(PLUGIN_ID) or {}
        except Exception:
            raw = {}

        config = dict(DEFAULT_CONFIG)
        if isinstance(raw, dict) and raw:
            config.update({k: v for k, v in raw.items() if v is not None})
        elif self.config:
            # 宿主尚未写入配置时（例如刚启用插件），沿用上一次的有效值。
            config.update(self.config)

        try:
            config["http_port"] = int(config.get("http_port") or DEFAULT_CONFIG["http_port"])
        except (TypeError, ValueError):
            config["http_port"] = DEFAULT_CONFIG["http_port"]
        try:
            config["poll_seconds"] = max(3, int(config.get("poll_seconds") or 10))
        except (TypeError, ValueError):
            config["poll_seconds"] = 10

        with self.lock:
            self.config = config

        configured = str(config.get("classisland_dir") or "").strip()
        ci_dir, source = self._resolve_dir(configured)
        with self.lock:
            self.ci_dir = ci_dir
            self.dir_source = source
            self.automation.ci_dir = ci_dir
            try:
                self.automation.file_name = str(config.get("automation_file") or "Default.json")
            except ValueError as exc:
                log_error(f"忽略不安全的自动化文件名：{exc}")
                self.automation.file_name = "Default.json"
                self.config["automation_file"] = "Default.json"
            self.bridge.set_dir(ci_dir)

    def _resolve_dir(self, configured: str) -> Tuple[Optional[Path], str]:
        """目录探测会扫注册表/进程，命中后缓存一段时间，避免每次轮询都扫。"""
        now = time.time()
        cached = self._discovery
        if cached and cached[0] == configured:
            ttl = 60 if self.ci_dir is not None else 15
            if now - cached[1] < ttl:
                return self.ci_dir, self.dir_source

        ci_dir, source = discover_classisland(configured)
        self._discovery = (configured, now)
        return ci_dir, source

    def save_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(self.config)
        merged.update(patch or {})
        _sdk_set_config(PLUGIN_ID, merged)
        self.config = merged
        self.reload_config()
        if not HAS_SDK:
            # 本地自检模式下保持内存配置，避免被默认值覆盖。
            self.config = merged
        return {"ok": True, "config": self.config}

    # -- 状态 -----------------------------------------------------------
    def compute(self) -> LessonState:
        with self.lock:
            ci_dir = self.ci_dir
        state = compute_state(ci_dir)
        # 这里只生成快照；不能覆盖 last_state，否则转换处理将失去旧状态。
        self.write_state_file(state)
        return state

    def write_state_file(self, state: LessonState) -> None:
        try:
            path = Path(__file__).resolve().parent / "runtime-state.json"
            write_json_atomic(path, state.to_dict())
        except Exception:
            pass

    def maybe_inject(self) -> None:
        config = self.config
        if not config.get("auto_inject_bridge", True):
            return
        if self.ci_dir is None:
            return
        status = self.bridge.status()
        bundle = Path(__file__).resolve().parent / "island-bridge" / "manifest.yml"
        bundle_version = ""
        if bundle.is_file():
            for line in bundle.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("version:"):
                    bundle_version = line.split(":", 1)[1].strip()
                    break
        if status["installed"] and status.get("version") == bundle_version:
            return
        result = self.bridge.inject()
        if result.get("ok"):
            self.injected_version = str(result.get("version") or "")
            log_info(f"已注入 ClassIsland 桥接插件 v{self.injected_version} -> {result.get('target')}")
            emit_event(
                "cuckoo.island.bridge.installed",
                {"version": self.injected_version, "target": result.get("target")},
            )
        else:
            log_error(f"注入桥接插件失败：{result.get('error')}")

    def tick(self) -> None:
        try:
            self.reload_config()
            self.process_ui_commands()
            self.maybe_inject()
            state = self.compute()
            self.handle_transition(state)
            self.publish_ui_state(state)
        except Exception:
            self.last_error = traceback.format_exc()
            log_error(f"轮询失败：{self.last_error}")

    def _latest_config(self) -> Dict[str, Any]:
        try:
            value = _sdk_get_config(PLUGIN_ID) or {}
            return dict(value) if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _write_config_fields(self, fields: Dict[str, Any]) -> None:
        if not HAS_SDK:
            return
        latest = self._latest_config()
        latest.update(fields)
        _sdk_set_config(PLUGIN_ID, latest)
        with self.lock:
            self.config.update(fields)

    def process_ui_commands(self) -> None:
        """消费配置页写入的操作队列；命令 ID 用于回执和去重。"""
        if not HAS_SDK:
            return
        persisted = self._latest_config()
        commands = persisted.get("ui_commands")
        if not isinstance(commands, list) or not commands:
            return

        processed_ids = set()
        results = []
        for command in commands[:20]:
            if not isinstance(command, dict):
                continue
            command_id = str(command.get("id") or "")
            command_type = str(command.get("type") or "")
            payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
            if not command_id or command_id in processed_ids:
                continue

            try:
                if command_type == "refresh":
                    result = {"ok": True, "message": "已刷新"}
                elif command_type == "automation_save":
                    requested = str(payload.get("file") or self.automation.file_name)
                    self.automation.file_name = requested
                    result = self.automation.save(payload.get("items"))
                elif command_type == "automation_insert":
                    requested = str(payload.get("file") or self.automation.file_name)
                    self.automation.file_name = requested
                    result = self.automation.insert_notification(
                        int(payload.get("index", -1)),
                        str(payload.get("title") or ""),
                        str(payload.get("message") or ""),
                    )
                elif command_type == "notify":
                    ok = self.bridge.push_notification(
                        str(payload.get("title") or "CuckooInterface"),
                        str(payload.get("message") or ""),
                        float(payload.get("duration") or 6),
                    )
                    result = {"ok": ok, "message": "提醒已加入队列" if ok else "提醒队列不可用"}
                elif command_type == "inject":
                    result = self.bridge.inject()
                elif command_type == "restart":
                    result = _restart_classisland()
                else:
                    result = {"ok": False, "error": f"未知操作：{command_type}"}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}

            processed_ids.add(command_id)
            results.append({
                "id": command_id,
                "type": command_type,
                "ok": bool(result.get("ok")),
                "message": str(result.get("message") or ""),
                "error": str(result.get("error") or ""),
                "backup": str(result.get("backup") or ""),
                "version": str(result.get("version") or ""),
                "updatedAt": datetime.now().isoformat(timespec="seconds"),
            })

        if not processed_ids:
            return

        # 再读一次最新配置，避免消费命令期间页面新追加的命令被覆盖。
        latest = self._latest_config()
        current_commands = latest.get("ui_commands")
        if not isinstance(current_commands, list):
            current_commands = []
        latest["ui_commands"] = [
            item for item in current_commands
            if not isinstance(item, dict) or str(item.get("id") or "") not in processed_ids
        ]
        current_results = latest.get("ui_results")
        if not isinstance(current_results, list):
            current_results = []
        latest["ui_results"] = (current_results + results)[-30:]
        _sdk_set_config(PLUGIN_ID, latest)
        with self.lock:
            self.config.update(latest)

    def publish_ui_state(self, state: LessonState) -> None:
        """把运行状态与当前自动化编辑数据写回宿主配置，供配置页轮询展示。"""
        snapshot = {
            "ok": True,
            "pluginId": PLUGIN_ID,
            "sdk": HAS_SDK,
            "config": {k: v for k, v in self.config.items()
                       if k not in ("ui_commands", "ui_results", "runtime_state", "automation_state")},
            "lesson": state.to_dict(),
            "classisland": {
                "dir": str(self.ci_dir) if self.ci_dir else "",
                "source": self.dir_source,
                "found": self.ci_dir is not None,
            },
            "bridge": self.bridge.status(),
            "lastError": self.last_error,
        }
        automation = self.automation.load()
        self._write_config_fields({
            "runtime_state": snapshot,
            "automation_state": automation,
        })

    def handle_transition(self, state: LessonState) -> None:
        if not state.ok:
            return
        key = (state.plan_id, state.status, state.lesson_index, state.subject)
        if key == self.last_key:
            with self.lock:
                self.last_state = state
            return

        with self.lock:
            previous = self.last_state
        previous_status = previous.status
        previous_subject = previous.subject
        self.last_key = key

        if self.config.get("emit_events", True):
            emit_event("cuckoo.island.state", state.to_dict())

        # 上课
        if state.status == "class" and (previous_status != "class" or previous_subject != state.subject):
            if self.config.get("emit_events", True):
                emit_event(
                    "cuckoo.island.lesson.started",
                    {
                        "subject": state.subject,
                        "teacher": state.teacher,
                        "index": state.lesson_index,
                        "count": state.lesson_count,
                        "startAt": state.start_at,
                        "endAt": state.end_at,
                    },
                )
            if self.config.get("notify_lesson_start", True):
                title = f"上课 · {state.subject or '课程'}"
                message = f"第 {state.lesson_index}/{state.lesson_count} 节 {state.start_at} - {state.end_at}"
                if state.teacher:
                    message += f" · {state.teacher}"
                self.bridge.push_notification(title, message, 8)

        # 下课
        if previous_status == "class" and state.status != "class":
            if self.config.get("emit_events", True):
                emit_event(
                    "cuckoo.island.lesson.ended",
                    {"subject": previous_subject, "next": state.next_subject, "nextStartAt": state.next_start_at},
                )
            if self.config.get("notify_lesson_end", True):
                title = f"下课 · {previous_subject or '课程'}"
                message = f"下一节：{state.next_subject}" if state.next_subject else "今天的课程结束了"
                if state.next_subject and state.next_start_at:
                    message += f"（{state.next_start_at}）"
                self.bridge.push_notification(title, message, 6)

        # 课间
        if state.status == "break" and previous_status == "class":
            if self.config.get("emit_events", True):
                emit_event("cuckoo.island.break.started", {"name": state.break_name})
            if self.config.get("notify_break", False):
                self.bridge.push_notification(
                    state.break_name or "课间",
                    f"休息 {seconds_to_text(state.remaining_seconds)}",
                    5,
                )

        # 仅在比较和处理完成后提交新状态，确保下一轮仍能看到旧状态。
        with self.lock:
            self.last_state = state

    def snapshot(self) -> Dict[str, Any]:
        state = self.compute()
        with self.lock:
            config = dict(self.config)
            ci_dir = self.ci_dir
            source = self.dir_source
        bridge = self.bridge.status()
        automation = self.automation.load()
        return {
            "ok": True,
            "pluginId": PLUGIN_ID,
            "sdk": HAS_SDK,
            "config": config,
            "classisland": {
                "dir": str(ci_dir) if ci_dir else "",
                "source": source,
                "found": ci_dir is not None,
            },
            "lesson": state.to_dict(),
            "bridge": bridge,
            "automation": {
                "ok": automation.get("ok", False),
                "error": automation.get("error", ""),
                "file": automation.get("file", config.get("automation_file")),
                "files": automation.get("files", []),
                "items": automation.get("items", []),
            },
            "lastError": self.last_error,
        }


SERVICE = IslandService()


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


# 操作通过宿主配置队列下发，不在插件侧开放本地 HTTP 服务。


def _restart_classisland() -> Dict[str, Any]:
    with SERVICE.lock:
        ci_dir = SERVICE.ci_dir
    if ci_dir is None:
        return {"ok": False, "error": "未找到 ClassIsland"}
    exe = ci_dir / "ClassIsland.exe"
    if not exe.is_file():
        return {"ok": False, "error": f"找不到 {exe}"}

    try:
        subprocess.run(
            ["taskkill", "/IM", "ClassIsland.exe", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass

    try:
        time.sleep(1.5)
        subprocess.Popen([str(exe)], cwd=str(ci_dir))
        return {"ok": True, "message": "ClassIsland 正在重启"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 循环 & 入口
# ---------------------------------------------------------------------------


def service_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        started = time.time()
        try:
            SERVICE.tick()
        except Exception:
            log_error(traceback.format_exc())
        interval = max(3, int(SERVICE.config.get("poll_seconds") or 10))
        elapsed = time.time() - started
        stop_event.wait(max(1.0, interval - elapsed))


def bootstrap() -> None:
    try:
        SERVICE.reload_config()
    except Exception:
        log_error(traceback.format_exc())

    stop_event = threading.Event()
    threading.Thread(target=service_loop, args=(stop_event,), name="cuckoo-island-loop", daemon=True).start()
    log_info("CuckooIsland 已启动（配置通过宿主配置存储同步）")


def cli_selftest() -> int:
    """本地自检：不依赖 CuckooInterface，直接打印当前课表状态。"""
    SERVICE.reload_config()
    state = SERVICE.compute()
    print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
    print("\n桥接状态：", json.dumps(SERVICE.bridge.status(), ensure_ascii=False, indent=2))
    automation = SERVICE.automation.load()
    print("\n自动化：", json.dumps({k: automation.get(k) for k in ("ok", "file", "files", "error")}, ensure_ascii=False, indent=2))
    for item in (automation.get("items") or [])[:5]:
        print("  -", item["index"], item["name"], "triggers=", item["triggers"], "actions=", item["actions"])
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(cli_selftest())
    bootstrap()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
else:
    if os.environ.get("CUCKOO_ISLAND_NO_BOOTSTRAP") != "1":
        try:
            bootstrap()
        except Exception:
            log_error(traceback.format_exc())
