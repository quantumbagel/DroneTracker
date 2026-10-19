"""Configuration loading: defaults, validation, and coordinate parsing."""
import copy
import math
import os
import re

from ruamel.yaml import YAML

from tracker.optics import Optics, SpeedMap

MODES = ("off", "on", "auto")
LOG_LEVELS = ("debug", "info", "warning", "error")

DEFAULTS = {
    "logs": "info",
    "camera": {
        "simulate": False,
        "ip": None,
        "username": "",
        "password": "",
        "request_timeout": 1.0,
        "lat": None,
        "lon": None,
        "alt": None,
        "offset": 0.0,
        "tilt_limits": [-90.0, 45.0],
        "park": {"pan": None, "tilt": -90.0},
        "park_after": 10.0,
        "disk": "SD_DISK",
        "stream_profile": None,
        "zoom": {"wide_hfov": 63.1, "max_zoom": 31.0, "table": None},
        "speed": {"pan_max": 60.0, "tilt_max": 60.0, "pan_table": None, "tilt_table": None},
    },
    "site": {"ref_alt_msl": None},
    "control": {
        "mode": "velocity",
        "hz": 10.0,
        "lookahead": 0.2,
        "kp": 2.0,
        "deadband": 0.2,
        "kz": 150.0,
        "zoom_deadband": 0.15,
        "min_step": 1.0,
    },
    "tracking": {
        "accel_noise": 3.0,
        "pos_sigma": 2.0,
        "vel_sigma": 0.5,
        "gate": 50.0,
        "max_extrapolation": 2.0,
        "stale_after": 1.5,
        "forget_after": 60.0,
    },
    "auto": {
        "startup_mode": "auto",
        "activate_after": 2.0,
        "deactivate_after": 5.0,
        "min_height": 3.0,
        "max_range": 2000.0,
        "min_elevation": -10.0,
        "sector": None,
    },
    "framing": {
        "drone_size": 1.0,
        "target_fraction": 0.15,
        "uncertainty_k": 2.0,
        "min_hfov": 4.0,
        "group": True,
        "max_group_hfov": 40.0,
        "group_fill": 0.8,
        "aspect": 16 / 9,
        "priority": [],
    },
    "recording": {
        "enabled": True,
        "dir": "recordings",
        "stop_after": 10.0,
        "log_interval": 0.5,
        "download_port": 15321,
    },
    "kafka": {
        "servers": ["localhost:9092"],
        "data_topic": "dronetracker-data",
        "command_topic": "dronetracker-command",
        "output_topic": "dronetracker-output",
    },
    "ingest": {
        "default_alt_ref": "msl",
        "legacy_velocity_frame": "ned",
        "max_clock_skew": 2.0,
        "default_latency": 0.0,
    },
}


class ConfigError(ValueError):
    pass


# Google Maps style, e.g. 35°45'31.2"N (the degree sign is optional, since it often gets lost when pasting)
_DMS = re.compile(r"""^(\d+(?:\.\d+)?)[°\s]+(\d+(?:\.\d+)?)['′]\s*(\d+(?:\.\d+)?)(?:["″]|'')\s*([NSEW])$""",
                  re.IGNORECASE)


def parse_coordinate(value, kind):
    """
    Parse a latitude or longitude from a number, a numeric string, or degrees/minutes/seconds.
    :param kind: "lat" or "lon"
    """
    if isinstance(value, bool) or value is None:
        raise ConfigError(f"camera/{kind} is required")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = str(value).strip()
        try:
            result = float(text)
        except ValueError:
            match = _DMS.match(text)
            if not match:
                raise ConfigError(f"camera/{kind}: can't parse coordinate {value!r}") from None
            degrees, minutes, seconds = (float(g) for g in match.groups()[:3])
            hemisphere = match.group(4).upper()
            if (kind == "lat") != (hemisphere in "NS"):
                raise ConfigError(f"camera/{kind}: hemisphere {hemisphere} doesn't match a {kind}itude")
            result = degrees + minutes / 60 + seconds / 3600
            if hemisphere in "SW":
                result = -result
    limit = 90 if kind == "lat" else 180
    if not -limit <= result <= limit:
        raise ConfigError(f"camera/{kind} out of range: {result}")
    return result


def load_config(path):
    with open(path) as config_file:
        raw = YAML(typ="safe").load(config_file) or {}
    return build_config(raw)


def build_config(raw):
    """Merge a raw config mapping over the defaults, apply environment overrides, and validate it."""
    cfg = _merge(copy.deepcopy(DEFAULTS), raw, "")
    for key in ("username", "password"):
        env = os.environ.get(f"DRONETRACKER_CAMERA_{key.upper()}")
        if env is not None:
            cfg["camera"][key] = env
    _validate(cfg)
    return cfg


def _merge(base, override, prefix):
    if not isinstance(override, dict):
        raise ConfigError(f"'{prefix.rstrip('/') or 'config'}' must be a mapping")
    for key, value in override.items():
        path = f"{prefix}{key}"
        if key not in base:
            raise ConfigError(f"unknown option '{path}'")
        if isinstance(base[key], dict):
            _merge(base[key], value or {}, path + "/")
        else:
            base[key] = value
    return base


def _number(value, name, minimum=None, maximum=None, positive=False, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{name} must be a number (got {value!r})")
    if positive and value <= 0:
        raise ConfigError(f"{name} must be greater than 0 (got {value})")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be at least {minimum} (got {value})")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be at most {maximum} (got {value})")
    return float(value)


def _choice(value, name, choices):
    if value not in choices:
        raise ConfigError(f"{name} must be one of {', '.join(choices)} (got {value!r})")
    return value


def _flag(value, name):
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be true or false (got {value!r})")
    return value


def _pair(value, name, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConfigError(f"{name} must be a list of two numbers")
    return [_number(v, name) for v in value]


def _validate(cfg):
    _choice(cfg["logs"], "logs", LOG_LEVELS)

    cam = cfg["camera"]
    _flag(cam["simulate"], "camera/simulate")
    if not cam["simulate"] and not cam["ip"]:
        raise ConfigError("camera/ip is required unless camera/simulate is true")
    cam["request_timeout"] = _number(cam["request_timeout"], "camera/request_timeout", positive=True)
    cam["lat"] = parse_coordinate(cam["lat"], "lat")
    cam["lon"] = parse_coordinate(cam["lon"], "lon")
    cam["alt"] = _number(cam["alt"], "camera/alt")
    cam["offset"] = _number(cam["offset"], "camera/offset")
    cam["tilt_limits"] = _pair(cam["tilt_limits"], "camera/tilt_limits")
    if cam["tilt_limits"][0] >= cam["tilt_limits"][1]:
        raise ConfigError("camera/tilt_limits must be [lowest, highest]")
    cam["park"]["pan"] = _number(cam["park"]["pan"], "camera/park/pan", optional=True)
    cam["park"]["tilt"] = _number(cam["park"]["tilt"], "camera/park/tilt", optional=True)
    cam["park_after"] = _number(cam["park_after"], "camera/park_after", minimum=0)
    cam["zoom"]["wide_hfov"] = _number(cam["zoom"]["wide_hfov"], "camera/zoom/wide_hfov", positive=True, maximum=179)
    cam["zoom"]["max_zoom"] = _number(cam["zoom"]["max_zoom"], "camera/zoom/max_zoom", minimum=1.001)
    cam["speed"]["pan_max"] = _number(cam["speed"]["pan_max"], "camera/speed/pan_max", positive=True)
    cam["speed"]["tilt_max"] = _number(cam["speed"]["tilt_max"], "camera/speed/tilt_max", positive=True)
    try:
        Optics(cam["zoom"])
        SpeedMap(cam["speed"]["pan_max"], cam["speed"]["pan_table"], "camera/speed/pan_table")
        SpeedMap(cam["speed"]["tilt_max"], cam["speed"]["tilt_table"], "camera/speed/tilt_table")
    except ValueError as error:
        raise ConfigError(str(error)) from None

    cfg["site"]["ref_alt_msl"] = _number(cfg["site"]["ref_alt_msl"], "site/ref_alt_msl", optional=True)

    ctl = cfg["control"]
    _choice(ctl["mode"], "control/mode", ("velocity", "position"))
    ctl["hz"] = _number(ctl["hz"], "control/hz", positive=True, maximum=50)
    for key in ("lookahead", "kp", "deadband", "kz", "zoom_deadband", "min_step"):
        ctl[key] = _number(ctl[key], f"control/{key}", minimum=0)

    trk = cfg["tracking"]
    for key in trk:
        trk[key] = _number(trk[key], f"tracking/{key}", positive=True)

    auto = cfg["auto"]
    _choice(auto["startup_mode"], "auto/startup_mode", MODES)
    auto["activate_after"] = _number(auto["activate_after"], "auto/activate_after", minimum=0)
    auto["deactivate_after"] = _number(auto["deactivate_after"], "auto/deactivate_after", minimum=0)
    auto["min_height"] = _number(auto["min_height"], "auto/min_height", optional=True)
    auto["max_range"] = _number(auto["max_range"], "auto/max_range", positive=True, optional=True)
    auto["min_elevation"] = _number(auto["min_elevation"], "auto/min_elevation", -90, 90, optional=True)
    auto["sector"] = _pair(auto["sector"], "auto/sector", optional=True)

    frm = cfg["framing"]
    frm["drone_size"] = _number(frm["drone_size"], "framing/drone_size", positive=True)
    frm["target_fraction"] = _number(frm["target_fraction"], "framing/target_fraction", positive=True, maximum=1)
    frm["uncertainty_k"] = _number(frm["uncertainty_k"], "framing/uncertainty_k", minimum=0)
    frm["min_hfov"] = _number(frm["min_hfov"], "framing/min_hfov", minimum=0, maximum=179)
    _flag(frm["group"], "framing/group")
    frm["max_group_hfov"] = _number(frm["max_group_hfov"], "framing/max_group_hfov", positive=True)
    frm["group_fill"] = _number(frm["group_fill"], "framing/group_fill", positive=True, maximum=1)
    frm["aspect"] = _number(frm["aspect"], "framing/aspect", positive=True)
    if not isinstance(frm["priority"], list):
        raise ConfigError("framing/priority must be a list of drone ids")
    frm["priority"] = [str(p) for p in frm["priority"]]

    rec = cfg["recording"]
    _flag(rec["enabled"], "recording/enabled")
    rec["dir"] = str(rec["dir"])
    rec["stop_after"] = _number(rec["stop_after"], "recording/stop_after", minimum=0)
    rec["log_interval"] = _number(rec["log_interval"], "recording/log_interval", positive=True)
    rec["download_port"] = int(_number(rec["download_port"], "recording/download_port", 1, 65535))

    kfk = cfg["kafka"]
    if isinstance(kfk["servers"], str):
        kfk["servers"] = [kfk["servers"]]
    kfk["servers"] = [str(s) if ":" in str(s) else f"{s}:9092" for s in kfk["servers"]]
    for key in ("data_topic", "command_topic", "output_topic"):
        kfk[key] = str(kfk[key])

    ing = cfg["ingest"]
    _choice(ing["default_alt_ref"], "ingest/default_alt_ref", ("msl", "rel"))
    _choice(ing["legacy_velocity_frame"], "ingest/legacy_velocity_frame", ("ned", "enu", "v1"))
    ing["max_clock_skew"] = _number(ing["max_clock_skew"], "ingest/max_clock_skew", minimum=0)
    ing["default_latency"] = _number(ing["default_latency"], "ingest/default_latency", minimum=0, maximum=5)
    if ing["default_alt_ref"] == "rel" and cfg["site"]["ref_alt_msl"] is None:
        raise ConfigError("ingest/default_alt_ref is 'rel', so site/ref_alt_msl must be set")
