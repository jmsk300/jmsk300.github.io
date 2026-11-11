"""Local-first desktop fishing conditions dashboard."""
from __future__ import annotations

import queue
import threading
from datetime import date, datetime
import tkinter as tk
from tkinter import messagebox, ttk
import uuid

import outing_helper as core


GREEN = "#244936"
BG = "#f1f4f0"
CARD = "#ffffff"
INK = "#1f332a"
MUTED = "#738078"
ACCENT = "#dbe9dc"


class FishingIntegrated:
    def __init__(self, root):
        self.root = root
        self.root.title("낚시 통합 도우미")
        self.root.geometry("1240x850")
        self.root.minsize(1050, 720)
        self.root.configure(bg=BG)
        self.root.option_add("*Font", ("Malgun Gothic", 10))
        self.jobs = queue.Queue()
        self.forecasts = []
        self.selected = None
        self.official_tide = None
        self.data_loaded_at = None
        self.config = core.config()
        self.status = tk.StringVar(value="오늘 지역별 낚시 환경을 불러오는 중입니다.")
        self.water = tk.StringVar(value="sea")
        self.region = tk.StringVar(value="전체 해안")
        self.station_code = tk.StringVar()
        self._styles()
        self._build()
        self.root.after(100, self._poll)
        self.refresh()
        self.root.after(60 * 60 * 1000, self._auto_refresh)

    def _styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=CARD, foreground=INK)
        s.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Malgun Gothic", 9))
        s.configure("Header.TLabel", background=GREEN, foreground="white", font=("Malgun Gothic", 21, "bold"))
        s.configure("HeaderSub.TLabel", background=GREEN, foreground="#d8e4dc", font=("Malgun Gothic", 9))
        s.configure("Section.TLabel", background=CARD, foreground=INK, font=("Malgun Gothic", 12, "bold"))
        s.configure("Big.TLabel", background=CARD, foreground=GREEN, font=("Malgun Gothic", 19, "bold"))
        s.configure("TButton", background="#e9eee8", foreground=GREEN, borderwidth=0, padding=(11, 8), font=("Malgun Gothic", 9, "bold"))
        s.map("TButton", background=[("active", "#dbe7dc")])
        s.configure("Go.TButton", background=GREEN, foreground="white")
        s.map("Go.TButton", background=[("active", "#173c2a")])
        s.configure("TCombobox", fieldbackground="white", bordercolor="#d8e0d8", padding=7)
        s.configure("Treeview", background="white", fieldbackground="white", foreground=INK, rowheight=31, borderwidth=0)
        s.configure("Treeview.Heading", background="#e9eee8", foreground=MUTED, font=("Malgun Gothic", 9, "bold"), relief="flat", padding=7)
        s.map("Treeview", background=[("selected", "#d7e7da")], foreground=[("selected", INK)])

    def _build(self):
        header = tk.Frame(self.root, bg=GREEN, padx=24, pady=17)
        header.pack(fill="x")
        ttk.Label(header, text="낚시 통합 도우미", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text="오늘의 포인트 · 시간대별 환경 · 지역별 바다 정보 · 나의 조과 기록", style="HeaderSub.TLabel").pack(anchor="w", pady=(4, 0))

        controls = ttk.Frame(self.root, padding=(18, 12, 18, 6))
        controls.pack(fill="x")
        bar = ttk.Frame(controls, style="Card.TFrame", padding=(13, 10))
        bar.pack(fill="x")
        ttk.Label(bar, text="지역 보기", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.region_box = ttk.Combobox(bar, textvariable=self.region, state="readonly", width=13,
                                       values=("전체 해안", "수도권", "동해", "서해", "남해", "제주", "민물 전체"))
        self.region_box.pack(side="left")
        self.region_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_region())
        ttk.Label(bar, text="물 유형", style="Muted.TLabel").pack(side="left", padx=(14, 7))
        ttk.Radiobutton(bar, text="바다", variable=self.water, value="sea", command=self._water_changed).pack(side="left")
        ttk.Radiobutton(bar, text="민물", variable=self.water, value="freshwater", command=self._water_changed).pack(side="left", padx=(5, 0))
        self.refresh_button = ttk.Button(bar, text="↻ 지금 새로고침", style="Go.TButton", command=self.refresh)
        self.refresh_button.pack(side="left", padx=(16, 6))
        ttk.Button(bar, text="조석 API 설정", command=self._settings).pack(side="left")
        ttk.Button(bar, text="조과 기록 입력", command=self._add_catch).pack(side="right")

        top = ttk.Frame(self.root, padding=(18, 6, 18, 10))
        top.pack(fill="both", expand=True)
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)
        top.rowconfigure(0, weight=1)
        rank_card = ttk.Frame(top, style="Card.TFrame", padding=13)
        rank_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        rank_card.rowconfigure(1, weight=1)
        rank_card.columnconfigure(0, weight=1)
        ttk.Label(rank_card, text="오늘 추천 포인트", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        cols = ("rank", "point", "score", "time", "wind", "wave", "temp")
        self.points_table = ttk.Treeview(rank_card, columns=cols, show="headings", selectmode="browse")
        specs = [("rank", "#", 38), ("point", "지역·포인트", 170), ("score", "환경 점수", 78), ("time", "좋은 시간", 75), ("wind", "바람", 63), ("wave", "파고", 58), ("temp", "수온", 58)]
        for key, title, width in specs:
            self.points_table.heading(key, text=title)
            self.points_table.column(key, width=width, minwidth=40, stretch=key == "point", anchor="w" if key == "point" else "center")
        self.points_table.grid(row=1, column=0, sticky="nsew")
        sc = ttk.Scrollbar(rank_card, orient="vertical", command=self.points_table.yview)
        sc.grid(row=1, column=1, sticky="ns")
        self.points_table.configure(yscrollcommand=sc.set)
        self.points_table.bind("<<TreeviewSelect>>", self._select_point)

        detail = ttk.Frame(top, style="Card.TFrame", padding=15)
        detail.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        detail.columnconfigure(0, weight=1)
        ttk.Label(detail, text="선택 포인트 브리핑", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.place_title = ttk.Label(detail, text="지역을 선택해 주세요", style="Big.TLabel")
        self.place_title.grid(row=1, column=0, sticky="w", pady=(8, 2))
        self.brief_var = tk.StringVar(value="최신 예보를 불러오고 있습니다.")
        ttk.Label(detail, textvariable=self.brief_var, style="Muted.TLabel", wraplength=430, justify="left").grid(row=2, column=0, sticky="ew", pady=(2, 12))
        cards = ttk.Frame(detail, style="Card.TFrame")
        cards.grid(row=3, column=0, sticky="ew")
        for col in range(2):
            cards.columnconfigure(col, weight=1)
        self.metric_vars = [tk.StringVar(value="—") for _ in range(4)]
        labels = ["현재 바람", "현재 파고", "현재 수온", "만조 · 간조"]
        for i, label in enumerate(labels):
            cell = ttk.Frame(cards, style="Card.TFrame", padding=(9, 8))
            cell.grid(row=i // 2, column=i % 2, sticky="ew", padx=3, pady=3)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            ttk.Label(cell, textvariable=self.metric_vars[i], style="Section.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(detail, text="이 지역의 과거 조과", style="Section.TLabel").grid(row=4, column=0, sticky="w", pady=(15, 5))
        self.history_var = tk.StringVar(value="저장된 출조 기록에서 같은 지역의 어종과 기록 횟수를 보여줍니다.")
        ttk.Label(detail, textvariable=self.history_var, style="Muted.TLabel", wraplength=430, justify="left").grid(row=5, column=0, sticky="ew")
        self.station_row = ttk.Frame(detail, style="Card.TFrame")
        self.station_row.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(self.station_row, text="KHOA 지점 코드", style="Muted.TLabel").pack(side="left")
        self.station_entry = ttk.Entry(self.station_row, textvariable=self.station_code, width=14)
        self.station_entry.pack(side="left", padx=7)
        ttk.Button(self.station_row, text="공식 조석 조회", command=self._official_tide).pack(side="left")

        bottom = ttk.Frame(self.root, padding=(18, 0, 18, 8))
        bottom.pack(fill="both", expand=True)
        table_card = ttk.Frame(bottom, style="Card.TFrame", padding=13)
        table_card.pack(fill="both", expand=True)
        table_card.rowconfigure(1, weight=1)
        table_card.columnconfigure(0, weight=1)
        headerline = ttk.Frame(table_card, style="Card.TFrame")
        headerline.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        ttk.Label(headerline, text="시간대별 낚시 환경", style="Section.TLabel").pack(side="left")
        self.updated_var = tk.StringVar(value="업데이트 대기")
        ttk.Label(headerline, textvariable=self.updated_var, style="Muted.TLabel").pack(side="right")
        hourly_cols = ("time", "score", "condition", "wind", "gust", "wave", "water", "tide", "rain")
        self.hourly_table = ttk.Treeview(table_card, columns=hourly_cols, show="headings", height=7)
        for key, title, width in [("time", "시간", 85), ("score", "점수", 65), ("condition", "평가", 78), ("wind", "풍속", 75), ("gust", "순간풍속", 75), ("wave", "파고", 68), ("water", "수온", 68), ("tide", "물 흐름·조석", 125), ("rain", "강수확률", 75)]:
            self.hourly_table.heading(key, text=title)
            self.hourly_table.column(key, width=width, minwidth=48, anchor="center")
        self.hourly_table.grid(row=1, column=0, sticky="nsew")
        hscroll = ttk.Scrollbar(table_card, orient="vertical", command=self.hourly_table.yview)
        hscroll.grid(row=1, column=1, sticky="ns")
        self.hourly_table.configure(yscrollcommand=hscroll.set)

        foot = tk.Frame(self.root, bg=BG, padx=22, pady=5)
        foot.pack(fill="x")
        ttk.Label(foot, textvariable=self.status, style="Muted.TLabel").pack(side="left")
        ttk.Label(foot, text="자료: Open-Meteo Forecast·Marine (ECMWF·NOAA·DWD·Copernicus 등) · KHOA  |  점수는 참고값이며 조과를 보장하지 않습니다.", style="Muted.TLabel").pack(side="right")

    def _apply_region(self):
        if self.region.get() == "민물 전체":
            self.water.set("freshwater")
        elif self.water.get() == "freshwater":
            self.water.set("sea")
        self.refresh()

    def _water_changed(self):
        if self.water.get() == "freshwater":
            self.region.set("민물 전체")
        elif self.region.get() == "민물 전체":
            self.region.set("전체 해안")
        self.refresh()

    def _auto_refresh(self):
        self.refresh()
        self.root.after(60 * 60 * 1000, self._auto_refresh)

    def refresh(self):
        if self.refresh_button.instate(["disabled"]):
            return
        self.refresh_button.configure(state="disabled", text="불러오는 중…")
        self.status.set("지역별 시간대 예보와 해양 정보를 새로 가져오고 있습니다.")
        water = self.water.get()
        day = date.today().isoformat()
        region = self.region.get()
        def work():
            values = core.fishing_forecast(water, day)
            if region not in {"전체 해안", "민물 전체"}:
                filters = {"수도권": ["인천"], "동해": ["강원", "부산"], "서해": ["인천", "충남", "군산"], "남해": ["여수", "통영", "부산"], "제주": ["제주"]}
                words = filters.get(region, [])
                values = [x for x in values if any(word in x["name"] for word in words)]
            return values
        self._run(work, "forecast")

    def _run(self, work, result_kind, context=None):
        def runner():
            try:
                self.jobs.put((result_kind, work(), context, None))
            except Exception as exc:
                self.jobs.put((result_kind, None, context, str(exc)))
        threading.Thread(target=runner, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, value, context, error = self.jobs.get_nowait()
                if kind == "forecast":
                    self.refresh_button.configure(state="normal", text="↻ 지금 새로고침")
                    if error:
                        self.status.set("자료를 불러오지 못했어요. 인터넷 연결을 확인하고 다시 새로고침해 주세요.")
                        messagebox.showerror("자료 조회 실패", error, parent=self.root)
                        continue
                    self.forecasts = value
                    self.data_loaded_at = datetime.now().astimezone()
                    self.updated_var.set("갱신 " + self.data_loaded_at.strftime("%Y-%m-%d %H:%M"))
                    self._render_points()
                    self.status.set(f"{len(value)}개 지역의 최신 예보를 받았습니다. 한 시간마다 자동으로 갱신합니다.")
                elif kind == "official_tide":
                    if error:
                        self.status.set("공식 조석 조회 실패: " + error)
                    else:
                        self.official_tide = value
                        self._render_selected()
                        self.status.set("국립해양조사원 조석예보를 받았습니다.")
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _render_points(self):
        for item in self.points_table.get_children():
            self.points_table.delete(item)
        for rank, point in enumerate(self.forecasts, 1):
            best = point.get("bestTime") or ""
            best_hour = best[11:16] if best else "자료 없음"
            best_row = next((row for row in point["hourly"] if row.get("time") == best), {})
            wave = self._fmt(best_row.get("waveM"), "m")
            water = self._fmt(best_row.get("waterTemp"), "°")
            wind = self._fmt(best_row.get("windKmh"), "km/h")
            self.points_table.insert("", "end", iid=str(rank - 1), values=(rank, point["name"], point.get("bestScore", 0), best_hour, wind, wave, water))
        if self.forecasts:
            self.points_table.selection_set("0")
            self.points_table.focus("0")
            self._show_selected(0)

    def _select_point(self, _event=None):
        selection = self.points_table.selection()
        if selection:
            self._show_selected(int(selection[0]))

    def _show_selected(self, index):
        if index < 0 or index >= len(self.forecasts):
            return
        self.selected = self.forecasts[index]
        self.official_tide = None
        codes = self.config.get("stationCodes", {})
        self.station_code.set(codes.get(self.selected["name"], ""))
        self._render_selected()

    def _fmt(self, value, unit=""):
        return f"{value:.1f}{unit}" if isinstance(value, (int, float)) else "자료 없음"

    def _render_selected(self):
        if not self.selected:
            return
        point = self.selected
        now = datetime.now().strftime("%Y-%m-%dT%H")
        current = next((row for row in point["hourly"] if row["time"][:13] >= now), point["hourly"][0] if point["hourly"] else {})
        best = max(point["hourly"], key=lambda r: r.get("score", 0), default={})
        self.place_title.configure(text=point["name"])
        best_time = best.get("time", "")
        when = best_time[11:16] if best_time else "자료 없음"
        self.brief_var.set(f"오늘 추천 시간 {when} · 환경 점수 {best.get('score', 0)}점. 바람과 파고가 낮고 조류가 움직이는 시간대를 우선 추천합니다.")
        self.metric_vars[0].set(self._fmt(current.get("windKmh"), " km/h"))
        self.metric_vars[1].set(self._fmt(current.get("waveM"), " m"))
        self.metric_vars[2].set(self._fmt(current.get("waterTemp"), "°C"))
        if self.official_tide and point.get("waterType") == "sea":
            ev = self.official_tide.get("events", [])
            self.metric_vars[3].set(" · ".join(f"{e['type']} {e['time']}" for e in ev[:4]) or "자료 없음")
        else:
            ev = point.get("tideEvents", [])
            self.metric_vars[3].set(" · ".join(f"{e['type']} {e['time'][11:16]}" for e in ev[:4]) or "모델 자료 없음")
        history = core.historical_catches(point, point["waterType"])
        top_species = ", ".join(f"{name}({count}회)" for name, count in history["species"][:6]) or "기록된 어종 없음"
        self.history_var.set(f"같은 지역 기록 {history['recordCount']}회 · 기록 마릿수 합계 {history['totalCatchCount']}\n주요 어종 기록: {top_species}\n‘조과 기록 입력’에서 어종과 마릿수를 적으면 지역별 과거 기록에 누적됩니다.")
        self._render_hourly(point)

    def _render_hourly(self, point):
        for item in self.hourly_table.get_children():
            self.hourly_table.delete(item)
        for row in point.get("hourly", []):
            t = row.get("time", "")
            hh = t[11:16]
            score = row.get("score", 0)
            condition = "좋음" if score >= 75 else "무난" if score >= 55 else "주의"
            wind = self._fmt(row.get("windKmh"), " km/h")
            gust = self._fmt(row.get("gustKmh"), " km/h")
            wave = self._fmt(row.get("waveM"), " m")
            water = self._fmt(row.get("waterTemp"), "°C")
            move = row.get("tideMove")
            tide = ("흐름 강" if move >= 0.45 else "흐름 보통" if move >= 0.2 else "흐름 약") if move is not None else "—"
            rain = self._fmt(row.get("rainChance"), "%")
            self.hourly_table.insert("", "end", values=(hh, f"{score}점", condition, wind, gust, wave, water, tide, rain))

    def _official_tide(self):
        if not self.selected:
            return
        code = self.station_code.get().strip()
        if not code:
            messagebox.showinfo("관측 지점 코드", "현재 포인트와 가까운 국립해양조사원 예보지점 코드를 입력하세요. 코드가 없으면 Open-Meteo 해수면 모델을 참고합니다.", parent=self.root)
            return
        codes = dict(self.config.get("stationCodes", {}))
        codes[self.selected["name"]] = code
        self.config["stationCodes"] = codes
        core.write_json(core.CONFIG_FILE, self.config)
        self.status.set("국립해양조사원 조석예보를 조회하고 있습니다.")
        self._run(lambda: core.tide_for(date.today().isoformat(), code), "official_tide")

    def _settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("국립해양조사원 API 설정")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=BG)
        box = ttk.Frame(dialog, style="Card.TFrame", padding=18)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        ttk.Label(box, text="공공데이터포털 인증키", style="Section.TLabel").pack(anchor="w")
        ttk.Label(box, text="조석 예보 인증키는 이 PC의 설정 파일에만 저장됩니다.", style="Muted.TLabel").pack(anchor="w", pady=(4, 10))
        key_var = tk.StringVar(value=self.config.get("khoaServiceKey", ""))
        entry = ttk.Entry(box, textvariable=key_var, width=58, show="•")
        entry.pack(fill="x")
        def save():
            self.config["khoaServiceKey"] = key_var.get().strip()
            self.config["stationCodes"] = dict(self.config.get("stationCodes", {}))
            core.write_json(core.CONFIG_FILE, self.config)
            dialog.destroy()
            self.status.set("API 설정을 저장했습니다. 선택 포인트의 관측소 코드도 등록하면 공식 조석을 조회할 수 있습니다.")
        row = ttk.Frame(box, style="Card.TFrame")
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="저장", style="Go.TButton", command=save).pack(side="right")
        ttk.Button(row, text="닫기", command=dialog.destroy).pack(side="right", padx=6)

    def _add_catch(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("과거 조과 기록")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=BG)
        box = ttk.Frame(dialog, style="Card.TFrame", padding=18)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        point_name = self.selected["name"] if self.selected else ""
        water_type = self.water.get()
        date_var = tk.StringVar(value=date.today().isoformat())
        loc_var = tk.StringVar(value=point_name)
        species_var = tk.StringVar()
        count_var = tk.StringVar()
        public_var = tk.BooleanVar(value=False)
        for label, var in [("출조 날짜 (YYYY-MM-DD)", date_var), ("장소", loc_var), ("어종", species_var), ("마릿수 (선택)", count_var)]:
            ttk.Label(box, text=label, style="Muted.TLabel").pack(anchor="w", pady=(7, 3))
            ttk.Entry(box, textvariable=var, width=48).pack(fill="x")
        ttk.Label(box, text="기억할 메모", style="Muted.TLabel").pack(anchor="w", pady=(7, 3))
        note = tk.Text(box, height=3, width=48, wrap="word", bg="#fbfcfa", fg=INK, relief="solid", bd=1)
        note.pack(fill="x")
        ttk.Checkbutton(box, text="홈페이지 공개 기록에 포함", variable=public_var).pack(anchor="w", pady=8)
        def save():
            try:
                day = date.fromisoformat(date_var.get().strip()).isoformat()
                count = int(count_var.get()) if count_var.get().strip() else None
                if count is not None and count < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("입력 확인", "날짜 형식이나 마릿수를 확인해 주세요.", parent=dialog)
                return
            if not loc_var.get().strip():
                messagebox.showinfo("장소 입력", "출조 장소를 입력해 주세요.", parent=dialog)
                return
            now = datetime.now().astimezone().isoformat(timespec="minutes")
            record = {"id": str(uuid.uuid4()), "date": day, "location": loc_var.get().strip(),
                      "waterType": water_type, "species": species_var.get().strip(), "catchCount": count,
                      "weather": {}, "tide": {}, "tideManual": "", "note": note.get("1.0", "end").strip(),
                      "publish": public_var.get(), "createdAt": now, "updatedAt": now}
            records = core.get_records()
            records.append(record)
            records.sort(key=lambda r: r.get("date", ""), reverse=True)
            core.write_json(core.PRIVATE_FILE, records)
            core.publish_records(records)
            dialog.destroy()
            if self.selected:
                self._render_selected()
            self.status.set("내 PC의 조과 기록에 저장했습니다.")
        row = ttk.Frame(box, style="Card.TFrame")
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="저장", style="Go.TButton", command=save).pack(side="right")
        ttk.Button(row, text="취소", command=dialog.destroy).pack(side="right", padx=6)


def main():
    root = tk.Tk()
    FishingIntegrated(root)
    root.mainloop()


if __name__ == "__main__":
    main()
