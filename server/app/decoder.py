from __future__ import annotations

import math
import re
from typing import Any


RAW_PATTERN = re.compile(r"^[0-9A-Fa-f]{14}(?:[0-9A-Fa-f]{14})?$")

DF_NAMES = {
    0: "短空空监视报文",
    4: "监视高度应答",
    5: "监视身份应答",
    11: "全呼应答",
    16: "长空空监视报文",
    17: "ADS-B 扩展电文",
    18: "非应答机扩展电文",
    19: "军用扩展电文",
    20: "Comm-B 高度应答",
    21: "Comm-B 身份应答",
    24: "Comm-D 扩展长度报文",
}

TC_NAMES = {
    **{code: "飞机识别与类别" for code in range(1, 5)},
    **{code: "地面位置" for code in range(5, 9)},
    **{code: "空中位置（气压高度）" for code in range(9, 19)},
    19: "空中速度",
    **{code: "空中位置（GNSS 高度）" for code in range(20, 23)},
    28: "飞机状态与紧急状态",
    29: "目标状态与自动驾驶信息",
    31: "飞机运行状态",
}

FLIGHT_STATUS = {
    0: "空中、无告警、无 SPI",
    1: "地面、无告警、无 SPI",
    2: "空中、有告警、无 SPI",
    3: "地面、有告警、无 SPI",
    4: "有告警、SPI 已置位",
    5: "无告警、SPI 已置位",
    6: "保留值",
    7: "保留值",
}

EMERGENCY_STATES = {
    0: "无紧急状态",
    1: "一般紧急状态",
    2: "医疗/救援任务",
    3: "最低燃油",
    4: "无线电通信故障",
    5: "非法干扰/劫机",
    6: "飞机失事或迫降",
    7: "保留值",
}

SURVEILLANCE_STATUS = {
    0: "无状态信息",
    1: "永久告警",
    2: "临时告警",
    3: "SPI 特殊位置识别",
}

IDENT_CHARSET = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######"


def _syndrome(raw: str) -> int:
    value = int(raw, 16)
    bit_length = len(raw) * 4
    polynomial = 0xFFF409
    for bit in range(bit_length - 1, 23, -1):
        if value & (1 << bit):
            value ^= polynomial << (bit - 24)
    return value & 0xFFFFFF


def _altitude_12(bits: str) -> tuple[str, str]:
    q_bit = bits[7]
    if q_bit == "1":
        altitude = int(bits[:7] + bits[8:], 2) * 25 - 1000
        return f"{altitude:,} ft", "Q=1，按 25 ft 量化解码"
    return f"0b{bits}", "Q=0，使用 Gillham/灰码；此处保留原始高度码"


def _squawk_13(bits: str) -> str:
    c1, a1, c2, a2, c4, a4, _, b1, d1, b2, d2, b4, d4 = [int(bit) for bit in bits]
    a = a4 * 4 + a2 * 2 + a1
    b = b4 * 4 + b2 * 2 + b1
    c = c4 * 4 + c2 * 2 + c1
    d = d4 * 4 + d2 * 2 + d1
    return f"{a}{b}{c}{d}"


def _surface_speed(code: int) -> str:
    if code == 0:
        return "无速度信息"
    if code == 1:
        return "0 kt（停止）"
    if 2 <= code <= 8:
        return f"约 {(code - 1) * 0.125:.3g} kt"
    if 9 <= code <= 12:
        return f"约 {1 + (code - 9) * 0.25:.3g} kt"
    if 13 <= code <= 38:
        return f"约 {2 + (code - 13) * 0.5:.3g} kt"
    if 39 <= code <= 93:
        return f"约 {15 + (code - 39):.0f} kt"
    if 94 <= code <= 108:
        return f"约 {70 + (code - 94) * 2:.0f} kt"
    if 109 <= code <= 123:
        return f"约 {100 + (code - 109) * 5:.0f} kt"
    if code == 124:
        return "至少 175 kt"
    return "保留值"


def decode_mode_s(raw: str) -> dict[str, Any]:
    normalized = raw.strip().upper()
    if not RAW_PATTERN.fullmatch(normalized):
        raise ValueError("Mode S message must contain 14 or 28 hexadecimal characters")

    binary = f"{int(normalized, 16):0{len(normalized) * 4}b}"
    fields: list[dict[str, str]] = []
    notes: list[str] = []

    def take(start: int, end: int) -> str:
        return binary[start - 1 : end]

    def add(
        start: int,
        end: int,
        name: str,
        value: Any,
        meaning: str,
        raw_bits: str | None = None,
    ) -> None:
        fields.append(
            {
                "bits": str(start) if start == end else f"{start}–{end}",
                "name": name,
                "raw": raw_bits if raw_bits is not None else take(start, end),
                "value": str(value),
                "meaning": meaning,
            }
        )

    df = int(take(1, 5), 2)
    df_name = DF_NAMES.get(df, "保留或较少使用的 Mode S 格式")
    add(1, 5, "下行格式 DF", df, df_name)
    summary = df_name
    type_code: int | None = None

    if df in {4, 5, 20, 21}:
        status = int(take(6, 8), 2)
        add(6, 8, "飞行状态 FS", status, FLIGHT_STATUS.get(status, "未知状态"))
    elif df == 18:
        control = int(take(6, 8), 2)
        add(6, 8, "控制字段 CF", control, "说明地址类型和扩展电文来源")
    else:
        capability = int(take(6, 8), 2)
        add(6, 8, "应答机能力 CA", capability, "Mode S 应答机能力/空地状态代码")

    if df in {11, 17, 18}:
        address = f"{int(take(9, 32), 2):06X}"
        add(9, 32, "飞机地址", address, "24 位 ICAO 地址或由 CF 指定的其他地址")

    if len(normalized) == 28 and df in {17, 18}:
        type_code = int(take(33, 37), 2)
        type_name = TC_NAMES.get(type_code, "保留或未定义的 ADS-B 类型")
        add(33, 37, "类型代码 TC", type_code, type_name)
        summary = type_name

        if 1 <= type_code <= 4:
            category = int(take(38, 40), 2)
            category_group = chr(ord("A") + type_code - 1)
            add(
                38,
                40,
                "发射器类别",
                f"{category_group}{category}",
                "描述飞机重量/用途类别；类别 0 表示未提供",
            )
            callsign = "".join(
                IDENT_CHARSET[int(take(start, start + 5), 2)]
                for start in range(41, 89, 6)
            ).replace("#", "").strip()
            add(41, 88, "呼号/航班号", callsign or "未填写", "8 个 IA-5 六位字符")
            summary = f"飞机识别：{callsign}" if callsign else type_name

        elif 5 <= type_code <= 8:
            movement = int(take(38, 44), 2)
            add(38, 44, "地面移动速度码", movement, _surface_speed(movement))
            track_valid = take(45, 45) == "1"
            add(45, 45, "地面航向有效", "是" if track_valid else "否", "决定后面的航向字段能否使用")
            track_value = int(take(46, 52), 2)
            track = track_value * 360 / 128
            add(46, 52, "地面航向", f"{track:.1f}°" if track_valid else "无效", "顺时针、正北为 0°")
            add(53, 53, "时间同步标志", int(take(53, 53), 2), "指示 CPR 数据是否与 UTC 同步")
            cpr_format = int(take(54, 54), 2)
            add(54, 54, "CPR 奇偶帧", "奇帧" if cpr_format else "偶帧", "通常需要一奇一偶两帧才能全局解算经纬度")
            add(55, 71, "CPR 纬度", int(take(55, 71), 2), "压缩位置原始值，不是直接的纬度")
            add(72, 88, "CPR 经度", int(take(72, 88), 2), "压缩位置原始值，不是直接的经度")
            summary = f"地面位置 · {_surface_speed(movement)}"

        elif 9 <= type_code <= 18 or 20 <= type_code <= 22:
            surveillance = int(take(38, 39), 2)
            add(38, 39, "监视状态 SS", surveillance, SURVEILLANCE_STATUS[surveillance])
            add(40, 40, "NIC 补充位", int(take(40, 40), 2), "用于位置完整性等级计算")
            altitude_value, altitude_note = _altitude_12(take(41, 52))
            altitude_kind = "GNSS 高度" if type_code >= 20 else "气压高度"
            add(41, 52, altitude_kind, altitude_value, altitude_note)
            add(53, 53, "时间同步标志", int(take(53, 53), 2), "指示 CPR 数据是否与 UTC 同步")
            cpr_format = int(take(54, 54), 2)
            add(54, 54, "CPR 奇偶帧", "奇帧" if cpr_format else "偶帧", "通常需要一奇一偶两帧才能全局解算经纬度")
            add(55, 71, "CPR 纬度", int(take(55, 71), 2), "17 位压缩纬度")
            add(72, 88, "CPR 经度", int(take(72, 88), 2), "17 位压缩经度")
            summary = f"{altitude_kind} {altitude_value} · CPR {'奇' if cpr_format else '偶'}帧"
            notes.append("页面上的实际经纬度由接收端结合多帧 CPR 数据计算；单条报文通常无法独立还原全球位置。")

        elif type_code == 19:
            subtype = int(take(38, 40), 2)
            add(38, 40, "速度子类型", subtype, "1/2 为地速分量，3/4 为空速和航向；2/4 使用超音速量程")
            add(41, 41, "意图改变标志", int(take(41, 41), 2), "指示意图信息是否发生改变")
            add(43, 45, "速度精度 NACv", int(take(43, 45), 2), "速度测量精度等级")
            scale = 4 if subtype in {2, 4} else 1
            if subtype in {1, 2}:
                ew_raw = int(take(47, 56), 2)
                ns_raw = int(take(58, 67), 2)
                ew = None if ew_raw == 0 else (ew_raw - 1) * scale * (-1 if take(46, 46) == "1" else 1)
                ns = None if ns_raw == 0 else (ns_raw - 1) * scale * (-1 if take(57, 57) == "1" else 1)
                add(46, 46, "东西方向", "西" if take(46, 46) == "1" else "东", "速度分量的符号")
                add(47, 56, "东西速度分量", "无数据" if ew is None else f"{abs(ew):.0f} kt", "原始值减 1 后按子类型缩放")
                add(57, 57, "南北方向", "南" if take(57, 57) == "1" else "北", "速度分量的符号")
                add(58, 67, "南北速度分量", "无数据" if ns is None else f"{abs(ns):.0f} kt", "原始值减 1 后按子类型缩放")
                if ew is not None and ns is not None:
                    ground_speed = math.hypot(ew, ns)
                    ground_track = math.degrees(math.atan2(ew, ns)) % 360
                    summary = f"地速 {ground_speed:.0f} kt · 航向 {ground_track:.0f}°"
                    notes.append(f"由东西/南北分量合成：地速 {ground_speed:.1f} kt，航向 {ground_track:.1f}°。")
            elif subtype in {3, 4}:
                heading_valid = take(46, 46) == "1"
                magnetic_heading = int(take(47, 56), 2) * 360 / 1024
                add(46, 46, "磁航向有效", "是" if heading_valid else "否", "决定磁航向字段能否使用")
                add(47, 56, "磁航向", f"{magnetic_heading:.1f}°" if heading_valid else "无效", "磁北为 0°")
                airspeed_type = "真空速 TAS" if take(57, 57) == "1" else "指示空速 IAS"
                airspeed_raw = int(take(58, 67), 2)
                airspeed = None if airspeed_raw == 0 else (airspeed_raw - 1) * scale
                add(57, 57, "空速类型", airspeed_type, "区分 IAS 与 TAS")
                add(58, 67, "空速", "无数据" if airspeed is None else f"{airspeed} kt", "原始值减 1 后按子类型缩放")
                summary = f"{airspeed_type} {airspeed} kt" if airspeed is not None else type_name
            else:
                notes.append("该速度子类型为保留值，因此只展示原始字段。")

            vertical_source = "气压高度" if take(68, 68) == "1" else "GNSS 高度"
            vertical_raw = int(take(70, 78), 2)
            vertical_rate = None if vertical_raw == 0 else (vertical_raw - 1) * 64 * (-1 if take(69, 69) == "1" else 1)
            add(68, 68, "垂直速度来源", vertical_source, "说明垂直速度依据哪种高度")
            add(69, 69, "垂直方向", "下降" if take(69, 69) == "1" else "上升", "垂直速度的符号")
            add(70, 78, "垂直速度", "无数据" if vertical_rate is None else f"{vertical_rate:+d} ft/min", "以 64 ft/min 为步进")
            difference_raw = int(take(82, 88), 2)
            difference = None if difference_raw == 0 else (difference_raw - 1) * 25 * (-1 if take(81, 81) == "1" else 1)
            add(81, 81, "GNSS/气压高度差符号", "负" if take(81, 81) == "1" else "正", "GNSS 高度减气压高度")
            add(82, 88, "GNSS/气压高度差", "无数据" if difference is None else f"{difference:+d} ft", "以 25 ft 为步进")

        elif type_code == 28:
            subtype = int(take(38, 40), 2)
            add(38, 40, "状态子类型", subtype, "子类型 1 携带紧急状态和 Mode A 应答码")
            if subtype == 1:
                emergency = int(take(41, 43), 2)
                add(41, 43, "紧急状态", emergency, EMERGENCY_STATES[emergency])
                squawk = _squawk_13(take(44, 56))
                add(44, 56, "Mode A 应答码", squawk, "四位八进制 Squawk 代码")
                add(57, 88, "保留字段", f"0x{int(take(57, 88), 2):08X}", "当前标准中保留")
                summary = f"{EMERGENCY_STATES[emergency]} · Squawk {squawk}"

        elif type_code == 29:
            subtype = int(take(38, 39), 2)
            add(38, 39, "目标状态子类型", subtype, "子类型 1 可包含选择高度和气压设定")
            if subtype == 1:
                add(40, 40, "选择高度来源", "FMS" if take(40, 40) == "1" else "MCP/FCU", "飞行管理系统或自动驾驶控制面板")
                selected_raw = int(take(41, 51), 2)
                selected = None if selected_raw == 0 else (selected_raw - 1) * 32
                add(41, 51, "选择高度", "无数据" if selected is None else f"{selected:,} ft", "飞行员/自动驾驶选择的目标高度")
                pressure_raw = int(take(52, 60), 2)
                pressure = None if pressure_raw == 0 else 800 + (pressure_raw - 1) * 0.8
                add(52, 60, "气压设定", "无数据" if pressure is None else f"{pressure:.1f} hPa", "高度表气压基准")
                add(61, 88, "状态/模式位", f"0x{int(take(61, 88), 2):07X}", "包含目标航向、精度和自动驾驶模式标志")
                summary = f"目标高度 {selected:,} ft" if selected is not None else type_name

        elif type_code == 31:
            subtype = int(take(38, 40), 2)
            add(38, 40, "运行状态子类型", subtype, "区分空中和地面运行状态")
            add(41, 56, "能力类别代码", f"0x{int(take(41, 56), 2):04X}", "应答机支持的 ADS-B 能力集合")
            add(57, 72, "运行模式代码", f"0x{int(take(57, 72), 2):04X}", "TCAS、单天线等运行模式标志")
            version = int(take(73, 75), 2)
            add(73, 75, "ADS-B 版本", version, "0=DO-260，1=DO-260A，2=DO-260B")
            add(76, 76, "NIC 补充 A", int(take(76, 76), 2), "位置完整性补充位")
            add(77, 80, "位置精度 NACp", int(take(77, 80), 2), "导航位置精度等级")
            add(81, 82, "垂直精度 GVA", int(take(81, 82), 2), "几何垂直精度等级")
            add(83, 84, "源完整性 SIL", int(take(83, 84), 2), "位置源超限概率等级")
            add(85, 88, "补充状态位", f"0b{take(85, 88)}", "NIC 气压、航向参考和 SIL 补充信息")
            summary = f"ADS-B 运行状态 · 版本 {version}"

        else:
            add(38, 88, "扩展电文载荷", f"0x{int(take(38, 88), 2):013X}", "该类型未定义或暂未细分，保留完整原始载荷")
            notes.append("这类 TC 没有稳定的公开字段定义，页面保留全部原始位，避免给出误导性解释。")

    elif df in {0, 4, 16, 20} and len(binary) >= 32:
        add(9, 13, "下行请求 DR", int(take(9, 13), 2), "地面询问与通信请求状态")
        add(14, 19, "监视/实用字段 UM", f"0b{take(14, 19)}", "询问器与监视状态信息")
        add(20, 32, "高度码 AC", f"0b{take(20, 32)}", "Mode C/Gillham 高度代码；需结合 M/Q 位解码")
    elif df in {5, 21} and len(binary) >= 32:
        add(9, 13, "下行请求 DR", int(take(9, 13), 2), "地面询问与通信请求状态")
        add(14, 19, "监视/实用字段 UM", f"0b{take(14, 19)}", "询问器与监视状态信息")
        squawk = _squawk_13(take(20, 32))
        add(20, 32, "Mode A 应答码", squawk, "四位八进制 Squawk 身份码")
        summary = f"{df_name} · Squawk {squawk}"

    if len(normalized) == 28 and df in {20, 21}:
        add(33, 88, "Comm-B 数据块 MB", f"0x{int(take(33, 88), 2):014X}", "内容由 BDS 寄存器决定，需结合请求上下文判定")
        notes.append("Comm-B 的 MB 数据块可能对应 BDS 1,0、4,0、5,0、6,0 等寄存器；仅靠单帧可能存在多种解释。")

    parity_start = len(binary) - 23
    parity_end = len(binary)
    remainder = _syndrome(normalized)
    if df in {17, 18}:
        integrity = remainder == 0
        parity_meaning = "CRC 校验通过" if integrity else "CRC 余数非零，报文可能损坏"
    else:
        integrity = None
        parity_meaning = "Mode S 校验/地址叠加字段；非零余数不一定代表报文损坏"
    add(
        parity_start,
        parity_end,
        "校验/奇偶字段",
        f"0x{int(take(parity_start, parity_end), 2):06X}",
        f"{parity_meaning}；综合余数 0x{remainder:06X}",
    )

    return {
        "df": df,
        "df_name": df_name,
        "type_code": type_code,
        "type_name": TC_NAMES.get(type_code) if type_code is not None else None,
        "summary": summary,
        "bit_length": len(binary),
        "binary": " ".join(binary[index : index + 8] for index in range(0, len(binary), 8)),
        "integrity": integrity,
        "fields": fields,
        "notes": notes,
    }
