"""Local fishing trip journal helper. Uses only the Python standard library."""
from __future__ import annotations

import json
import re
import threading
import uuid
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
APP_PAGE = ROOT / "planner" / "index.html"
PRIVATE_FILE = ROOT / "outing_records.json"
PUBLIC_FILE = ROOT / "data" / "outings.json"
CONFIG_FILE = ROOT / "outing_config.json"
HOST, PORT = "127.0.0.1", 8765
UA = "JinhoFishingJournal/1.0 (outing helper)"


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def get_records():
    records = read_json(PRIVATE_FILE, [])
    return records if isinstance(records, list) else []


def publish_records(records):
    public = []
    for record in records:
        if not record.get("publish"):
            continue
        safe = {key: value for key, value in record.items() if key not in {"latitude", "longitude", "publish"}}
        public.append(safe)
    public.sort(key=lambda entry: (entry.get("date", ""), entry.get("createdAt", "")), reverse=True)
    write_json(PUBLIC_FILE, {"updatedAt": datetime.now().astimezone().isoformat(timespec="minutes"), "records": public})


def config():
    value = read_json(CONFIG_FILE, {})
    return value if isinstance(value, dict) else {}


def api_json(url, timeout=18):
    request = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def geocode(place):
    query = urlencode({"name": place, "count": 5, "language": "ko", "countryCode": "KR", "format": "json"})
    data = api_json("https://geocoding-api.open-meteo.com/v1/search?" + query)
    found = data.get("results") or []
    if not found:
        raise ValueError("장소를 찾지 못했어요. 시·군 이름으로 다시 검색해 주세요.")
    return [{
        "name": item.get("name", place), "admin1": item.get("admin1", ""), "admin2": item.get("admin2", ""),
        "latitude": item["latitude"], "longitude": item["longitude"], "timezone": item.get("timezone", "Asia/Seoul")
    } for item in found]


WEATHER_LABELS = {
    0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "짙은 안개",
    51: "이슬비", 53: "이슬비", 55: "강한 이슬비", 56: "어는 이슬비", 57: "강한 어는 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비", 66: "어는 비", 67: "강한 어는 비",
    71: "약한 눈", 73: "눈", 75: "강한 눈", 77: "싸락눈", 80: "소나기", 81: "소나기", 82: "강한 소나기",
    85: "눈 소나기", 86: "강한 눈 소나기", 95: "뇌우", 96: "우박 동반 뇌우", 99: "강한 우박 동반 뇌우"
}


def weather_for(day, place, lat=None, lon=None):
    if lat is None or lon is None:
        loc = geocode(place)[0]
        lat, lon = loc["latitude"], loc["longitude"]
        place = ", ".join(part for part in [loc["name"], loc["admin2"], loc["admin1"]] if part)
    target = date.fromisoformat(day)
    today = date.today()
    common = {"latitude": lat, "longitude": lon, "timezone": "Asia/Seoul",
              "daily": "weather_code,temperature_2m_min,temperature_2m_max,precipitation_sum,wind_speed_10m_max,wind_direction_10m_dominant",
              "start_date": day, "end_date": day}
    if target < today - timedelta(days=7):
        host = "https://archive-api.open-meteo.com/v1/archive"
    else:
        if target > today + timedelta(days=15):
            raise ValueError("날씨 예보는 오늘부터 16일 이내 날짜만 조회할 수 있어요. 더 먼 날짜는 출조 후 기록해 주세요.")
        host = "https://api.open-meteo.com/v1/forecast"
        common.pop("start_date")
        common.pop("end_date")
        common["forecast_days"] = min(16, max(1, (target - today).days + 1))
        if target < today:
            common["past_days"] = min(7, (today - target).days)
    data = api_json(host + "?" + urlencode(common))
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    if day not in dates:
        raise ValueError("선택한 날짜의 날씨 자료가 아직 제공되지 않아요. 날씨를 직접 입력해 저장할 수 있어요.")
    i = dates.index(day)
    value = lambda field: (daily.get(field) or [None] * len(dates))[i]
    code = value("weather_code")
    direction = value("wind_direction_10m_dominant")
    compass = "북 북북동 북동 동북동 동 동남동 남동 남남동 남 남남서 남서 서남서 서 서북서 북서 북북서".split()
    result = {
        "place": place, "latitude": float(lat), "longitude": float(lon),
        "summary": WEATHER_LABELS.get(code, "날씨 자료"), "weatherCode": code,
        "minTemp": value("temperature_2m_min"), "maxTemp": value("temperature_2m_max"),
        "rainMm": value("precipitation_sum"), "windKmh": value("wind_speed_10m_max"),
        "windDirection": compass[round(float(direction) / 22.5) % 16] if direction is not None else None,
        "source": "Open-Meteo · 재분석/예보", "fetchedAt": datetime.now().astimezone().isoformat(timespec="minutes")
    }
    return result


def recursive_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from recursive_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from recursive_dicts(child)


def pick(row, names):
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] not in (None, ""):
            return lowered[name.lower()]
    return None


def tide_for(day, station_code):
    key = unquote(config().get("khoaServiceKey", "").strip())
    if not key:
        raise ValueError("물때 자동 조회에는 공공데이터포털 인증키가 필요해요. 아래 설정에서 등록하거나 만조·간조를 직접 입력해 주세요.")
    params = {"serviceKey": key, "type": "json", "obsCode": station_code, "reqDate": day.replace("-", ""), "pageNo": 1, "numOfRows": 30}
    endpoint = "https://apis.data.go.kr/1192136/tideFcstHghLw/GetTideFcstHghLwApiService?" + urlencode(params)
    data = api_json(endpoint)
    header = next((obj for obj in recursive_dicts(data) if "resultCode" in obj or "resultMsg" in obj), {})
    if header and str(header.get("resultCode", "00")) not in {"00", "0", "0000"}:
        raise ValueError("조석 API 응답: " + str(header.get("resultMsg", "인증키와 관측소 코드를 확인해 주세요.")))
    events = []
    for row in recursive_dicts(data):
        raw_time = pick(row, ["predcDate", "predcDatetime", "predcDt", "predcTm", "predTime", "obsTime", "fcstTime", "time"])
        level = pick(row, ["predcLevel", "predcLvl", "predcHgt", "predcHgh", "tideLevel", "tideLvl", "level", "wl"])
        kind = pick(row, ["hlName", "hlCls", "tideType", "predcType", "obsLvlNm", "gubun", "typeName"])
        if raw_time is None and level is None:
            continue
        if raw_time is not None:
            digits = re.sub(r"\D", "", str(raw_time))
            time_text = f"{digits[-4:-2]}:{digits[-2:]}" if len(digits) >= 4 else str(raw_time)
        else:
            time_text = ""
        type_text = str(kind or "")
        if not any(word in type_text for word in ("고", "저", "만", "간", "high", "low", "H", "L")):
            code = str(pick(row, ["hlCode", "predcCode", "tideCode"]) or "").upper()
            type_text = "만조" if code in {"H", "HW", "1"} else "간조" if code in {"L", "LW", "2"} else type_text or "조위"
        label = "만조" if any(word in type_text.lower() for word in ("고", "만", "high", "hw")) else "간조" if any(word in type_text.lower() for word in ("저", "간", "low", "lw")) else type_text
        try:
            level_value = round(float(str(level).replace(",", "")), 1) if level is not None else None
        except ValueError:
            level_value = None
        events.append({"time": time_text, "type": label, "levelCm": level_value})
    deduped = {(event["time"], event["type"]): event for event in events if event["time"]}
    events = sorted(deduped.values(), key=lambda event: event["time"])
    if not events:
        raise ValueError("조석 API에서 만조·간조 자료를 찾지 못했어요. 관측소 코드를 확인하거나 직접 입력해 주세요.")
    return {"stationCode": station_code, "events": events, "source": "국립해양조사원 조석예보", "fetchedAt": datetime.now().astimezone().isoformat(timespec="minutes")}


COASTAL_POINTS = [
    {"name": "인천 영종도", "latitude": 37.46, "longitude": 126.44, "aliases": ["영종", "인천"]},
    {"name": "강원 속초", "latitude": 38.19, "longitude": 128.61, "aliases": ["속초"]},
    {"name": "강원 주문진", "latitude": 37.89, "longitude": 128.83, "aliases": ["주문진", "강릉"]},
    {"name": "충남 태안 안면도", "latitude": 36.51, "longitude": 126.35, "aliases": ["태안", "안면도"]},
    {"name": "전북 군산 선유도", "latitude": 35.81, "longitude": 126.41, "aliases": ["군산", "선유도"]},
    {"name": "전남 여수 돌산", "latitude": 34.62, "longitude": 127.75, "aliases": ["여수", "돌산"]},
    {"name": "경남 통영 미륵도", "latitude": 34.82, "longitude": 128.42, "aliases": ["통영", "미륵도"]},
    {"name": "부산 기장", "latitude": 35.18, "longitude": 129.22, "aliases": ["부산", "기장"]},
    {"name": "제주 성산", "latitude": 33.46, "longitude": 126.93, "aliases": ["제주", "성산"]},
]
FRESHWATER_POINTS = [
    {"name": "경기 파주 공릉천", "latitude": 37.84, "longitude": 126.79, "aliases": ["파주", "공릉천"]},
    {"name": "강원 춘천 의암호", "latitude": 37.90, "longitude": 127.73, "aliases": ["춘천", "의암호"]},
    {"name": "충북 충주호", "latitude": 36.99, "longitude": 127.99, "aliases": ["충주", "충주호"]},
    {"name": "대전 대청호", "latitude": 36.48, "longitude": 127.49, "aliases": ["대청호", "대전"]},
]


def _multi_payload(payload, index):
    if isinstance(payload, list):
        return payload[index] if index < len(payload) else {}
    return payload if index == 0 else {}


def _number(values, index):
    try:
        value = values[index]
        return float(value) if value is not None else None
    except (IndexError, TypeError, ValueError):
        return None


def fishing_score(row, water_type):
    """Transparent environmental heuristic (not a catch guarantee)."""
    factors = []
    wind = row.get("windKmh")
    if wind is not None:
        factors.append((max(0, min(100, 100 - max(0, wind - 5) * 5)), 0.30))
    wave = row.get("waveM")
    if water_type == "sea" and wave is not None:
        factors.append((max(0, min(100, 100 - max(0, wave - 0.2) * 45)), 0.30))
    rain = row.get("rainChance")
    if rain is not None:
        factors.append((max(0, 100 - rain * 0.75), 0.18))
    temp = row.get("airTemp")
    if temp is not None:
        factors.append((max(0, 100 - abs(temp - 19) * 3.5), 0.12))
    tide_move = row.get("tideMove")
    if water_type == "sea" and tide_move is not None:
        factors.append((min(100, tide_move * 180), 0.10))
    total_weight = sum(weight for _, weight in factors)
    return round(sum(score * weight for score, weight in factors) / total_weight) if total_weight else 0


def fishing_forecast(water_type="sea", day=None):
    """Fetch today's hourly forecast for built-in Korean fishing areas."""
    target = date.fromisoformat(day) if day else date.today()
    points = COASTAL_POINTS if water_type == "sea" else FRESHWATER_POINTS
    latitudes = ",".join(str(point["latitude"]) for point in points)
    longitudes = ",".join(str(point["longitude"]) for point in points)
    weather_fields = "temperature_2m,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m"
    weather_query = urlencode({
        "latitude": latitudes, "longitude": longitudes, "hourly": weather_fields,
        "forecast_days": 2, "timezone": "Asia/Seoul", "wind_speed_unit": "kmh"
    })
    weather_data = api_json("https://api.open-meteo.com/v1/forecast?" + weather_query)
    marine_data = None
    if water_type == "sea":
        marine_fields = "wave_height,sea_surface_temperature,sea_level_height_msl,ocean_current_velocity"
        marine_query = urlencode({
            "latitude": latitudes, "longitude": longitudes, "hourly": marine_fields,
            "forecast_days": 2, "timezone": "Asia/Seoul", "length_unit": "metric", "cell_selection": "sea"
        })
        marine_data = api_json("https://marine-api.open-meteo.com/v1/marine?" + marine_query)

    output = []
    local_now = datetime.now().astimezone().strftime("%Y-%m-%dT%H")
    for index, point in enumerate(points):
        weather = _multi_payload(weather_data, index).get("hourly", {})
        marine = _multi_payload(marine_data, index).get("hourly", {}) if marine_data is not None else {}
        times = weather.get("time", [])
        marine_times = marine.get("time", [])
        marine_indices = {value: i for i, value in enumerate(marine_times)}
        hourly = []
        for i, timestamp in enumerate(times):
            if not timestamp.startswith(target.isoformat()):
                continue
            mi = marine_indices.get(timestamp)
            row = {
                "time": timestamp,
                "airTemp": _number(weather.get("temperature_2m", []), i),
                "rainChance": _number(weather.get("precipitation_probability", []), i),
                "rainMm": _number(weather.get("precipitation", []), i),
                "windKmh": _number(weather.get("wind_speed_10m", []), i),
                "gustKmh": _number(weather.get("wind_gusts_10m", []), i),
                "windDirection": _number(weather.get("wind_direction_10m", []), i),
                "waveM": _number(marine.get("wave_height", []), mi) if mi is not None else None,
                "waterTemp": _number(marine.get("sea_surface_temperature", []), mi) if mi is not None else None,
                "seaLevel": _number(marine.get("sea_level_height_msl", []), mi) if mi is not None else None,
                "currentKmh": _number(marine.get("ocean_current_velocity", []), mi) if mi is not None else None,
            }
            hourly.append(row)
        for i, row in enumerate(hourly):
            before = hourly[max(0, i - 1)].get("seaLevel")
            after = hourly[min(len(hourly) - 1, i + 1)].get("seaLevel")
            row["tideMove"] = abs(after - before) if before is not None and after is not None else None
            row["score"] = fishing_score(row, water_type)
        tide_events = []
        for i in range(1, len(hourly) - 1):
            prev, current, nxt = (hourly[j].get("seaLevel") for j in (i - 1, i, i + 1))
            if prev is None or current is None or nxt is None:
                continue
            if current >= prev and current > nxt:
                tide_events.append({"time": hourly[i]["time"], "type": "만조 추정", "levelMsl": current})
            elif current <= prev and current < nxt:
                tide_events.append({"time": hourly[i]["time"], "type": "간조 추정", "levelMsl": current})
        upcoming = [row for row in hourly if row["time"][:13] >= local_now] if target == date.today() else hourly
        ranked_hours = sorted(upcoming or hourly, key=lambda row: row["score"], reverse=True)
        best = ranked_hours[0] if ranked_hours else {}
        output.append({
            **point, "waterType": water_type, "hourly": upcoming or hourly,
            "bestTime": best.get("time"), "bestScore": best.get("score", 0),
            "tideEvents": tide_events, "fetchedAt": datetime.now().astimezone().isoformat(timespec="minutes"),
            "source": "Open-Meteo Forecast API" + (" · Open-Meteo Marine API" if water_type == "sea" else "")
        })
    output.sort(key=lambda item: item["bestScore"], reverse=True)
    return output


def historical_catches(point, water_type="sea"):
    aliases = [point.get("name", "")] + point.get("aliases", [])
    aliases = [re.sub(r"\s+", "", name).lower() for name in aliases if name]
    records = read_json(PRIVATE_FILE, [])
    matches = []
    for record in records if isinstance(records, list) else []:
        location = re.sub(r"\s+", "", str(record.get("location", ""))).lower()
        record_water = record.get("waterType", "sea")
        if record_water == water_type and any(alias in location or location in alias for alias in aliases if len(alias) >= 2):
            matches.append(record)
    species = {}
    total_catches = 0
    for record in matches:
        for item in re.split(r"[,，、/ ]+", str(record.get("species", ""))):
            if item:
                species[item] = species.get(item, 0) + 1
        try:
            total_catches += max(0, int(record.get("catchCount") or 0))
        except (TypeError, ValueError):
            pass
    return {"recordCount": len(matches), "totalCatchCount": total_catches,
            "species": sorted(species.items(), key=lambda pair: (-pair[1], pair[0])), "records": matches}


class Handler(BaseHTTPRequestHandler):
    server_version = "OutingHelper/1.0"

    def log_message(self, fmt, *args):
        print("[출조도우미] " + fmt % args)

    def send_json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 500_000:
            raise ValueError("요청이 너무 큽니다.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            if parsed.path in {"/", "/planner/", "/planner/index.html"}:
                raw = APP_PAGE.read_bytes()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
            if parsed.path == "/api/outings":
                return self.send_json({"records": get_records()})
            if parsed.path == "/api/settings":
                return self.send_json({"khoaConfigured": bool(config().get("khoaServiceKey"))})
            if parsed.path == "/api/geocode":
                return self.send_json({"results": geocode(qs.get("q", [""])[0])})
            if parsed.path == "/api/weather":
                return self.send_json({"weather": weather_for(qs["date"][0], qs.get("place", [""])[0], qs.get("lat", [None])[0], qs.get("lon", [None])[0])})
            if parsed.path == "/api/tide":
                return self.send_json({"tide": tide_for(qs["date"][0], qs["station"][0])})
            return self.send_json({"error": "찾을 수 없는 주소입니다."}, 404)
        except (ValueError, KeyError, URLError, HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            message = exc.reason if isinstance(exc, (URLError, HTTPError)) else str(exc)
            return self.send_json({"error": message or "외부 자료를 불러오지 못했습니다."}, 400)

    def do_POST(self):
        try:
            payload = self.read_body()
            if self.path == "/api/settings":
                key = str(payload.get("khoaServiceKey", "")).strip()
                if key:
                    write_json(CONFIG_FILE, {"khoaServiceKey": key})
                else:
                    CONFIG_FILE.unlink(missing_ok=True)
                return self.send_json({"ok": True, "khoaConfigured": bool(key)})
            if self.path == "/api/outings":
                day = date.fromisoformat(str(payload.get("date", ""))).isoformat()
                location = str(payload.get("location", "")).strip()
                if not location:
                    raise ValueError("장소를 입력해 주세요.")
                record = {
                    "id": str(payload.get("id") or uuid.uuid4()), "date": day, "location": location[:100],
                    "waterType": "sea" if payload.get("waterType") == "sea" else "freshwater",
                    "species": str(payload.get("species", "")).strip()[:60], "weather": payload.get("weather") or {},
                    "tide": payload.get("tide") or {}, "tideManual": str(payload.get("tideManual", "")).strip()[:600],
                    "note": str(payload.get("note", "")).strip()[:1200], "publish": bool(payload.get("publish")),
                    "updatedAt": datetime.now().astimezone().isoformat(timespec="minutes")
                }
                if payload.get("latitude") is not None and payload.get("longitude") is not None:
                    record["latitude"], record["longitude"] = float(payload["latitude"]), float(payload["longitude"])
                records = get_records()
                index = next((i for i, old in enumerate(records) if old.get("id") == record["id"]), None)
                if index is None:
                    record["createdAt"] = record["updatedAt"]
                    records.append(record)
                else:
                    record["createdAt"] = records[index].get("createdAt", record["updatedAt"])
                    records[index] = record
                records.sort(key=lambda item: (item.get("date", ""), item.get("createdAt", "")), reverse=True)
                write_json(PRIVATE_FILE, records)
                publish_records(records)
                return self.send_json({"ok": True, "record": record, "records": records})
            if self.path.startswith("/api/outings/delete/"):
                record_id = self.path.rsplit("/", 1)[-1]
                records = [record for record in get_records() if record.get("id") != record_id]
                write_json(PRIVATE_FILE, records); publish_records(records)
                return self.send_json({"ok": True, "records": records})
            return self.send_json({"error": "찾을 수 없는 주소입니다."}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.send_json({"error": str(exc)}, 400)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    if not APP_PAGE.exists():
        raise SystemExit("planner/index.html 파일이 없습니다. 홈페이지 저장소 폴더에서 실행해 주세요.")
    try:
        server = LocalServer((HOST, PORT), Handler)
    except OSError as exc:
        raise SystemExit(f"로컬 포트 {PORT}를 열 수 없습니다. 다른 프로그램이 사용 중인지 확인해 주세요.\n{exc}")
    url = f"http://{HOST}:{PORT}/planner/"
    print("출조 도우미가 실행 중입니다:", url)
    print("종료하려면 이 창에서 Ctrl+C를 누르세요.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n출조 도우미를 종료합니다.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
