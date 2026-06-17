import json
import random
import socket
import socketserver
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from tkinter import messagebox, ttk


TIME_FORMAT = "%H:%M"
HISTORY_FILE = Path(__file__).with_name("student_daily_life_history.json")
MINUTE_MS = 60_000
EXERCISE_REMINDER_MINUTES = 15
MOVE_IDEAS = [
    "Run in place for 30 seconds.",
    "Do 10 jumping jacks.",
    "Stretch your arms and shoulders.",
    "Walk around the room twice.",
    "Do 8 squats slowly.",
    "Lie down, roll gently to the side, then stand up and reset.",
]


@dataclass
class StudyBlock:
    start: datetime
    end: datetime
    title: str
    block_type: str
    reason: str


def parse_time(value):
    return datetime.strptime(value.strip(), TIME_FORMAT)


def format_time(value):
    return value.strftime(TIME_FORMAT)


def minutes_between(start, end):
    if end <= start:
        end += timedelta(days=1)
    return int((end - start).total_seconds() // 60)


def split_items(text):
    return [item.strip() for item in text.split(",") if item.strip()]


def detect_energy_level(text):
    value = text.lower()
    if "high" in value or "fresh" in value or "active" in value:
        return "high"
    if "low" in value or "tired" in value or "sleepy" in value:
        return "low"
    return "medium"


def subject_priority(subject, goal, worries):
    text = f"{subject} {goal} {worries}".lower()
    score = 50
    hard_words = ["hard", "difficult", "weak", "exam", "test", "quiz", "late", "behind"]
    easy_words = ["easy", "revision", "review", "reading"]

    for word in hard_words:
        if word in text:
            score += 8
    for word in easy_words:
        if word in text:
            score -= 4

    if subject.lower() in goal.lower():
        score += 30
    if subject.lower() in worries.lower():
        score += 20

    return score


def choose_session_length(total_minutes, energy_level):
    if total_minutes < 90:
        return 25
    if energy_level == "high":
        return 50
    if energy_level == "low":
        return 25
    return 40


def choose_break_length(energy_level):
    if energy_level == "low":
        return 12
    if energy_level == "high":
        return 8
    return 10


def smart_movement_for_energy(energy_level):
    if energy_level == "low":
        return random.choice([
            "Do slow neck and shoulder stretches for 45 seconds.",
            "Walk calmly around the room and drink water.",
            "Take 5 deep breaths, then stretch your back.",
        ])
    if energy_level == "high":
        return random.choice([
            "Do 10 jumping jacks.",
            "Run in place for 30 seconds.",
            "Do 8 quick squats, then sit back down.",
        ])
    return random.choice(MOVE_IDEAS)


def smart_plan(name, morning, afternoon, evening, free_start, free_end, subjects, goal, worries, energy):
    start = parse_time(free_start)
    end = parse_time(free_end)
    total_minutes = minutes_between(start, end)
    energy_level = detect_energy_level(energy)
    session_minutes = choose_session_length(total_minutes, energy_level)
    break_minutes = choose_break_length(energy_level)

    ranked_subjects = sorted(
        subjects,
        key=lambda subject: subject_priority(subject, goal, worries),
        reverse=True,
    )

    blocks = []
    current = start
    remaining = total_minutes
    index = 0

    if total_minutes >= 35:
        warmup_end = current + timedelta(minutes=5)
        blocks.append(
            StudyBlock(
                current,
                warmup_end,
                "AI warm-up",
                "setup",
                "Write the exact goal for this study window.",
            )
        )
        current = warmup_end
        remaining -= 5

    while remaining >= 20 and ranked_subjects:
        subject = ranked_subjects[index % len(ranked_subjects)]
        actual_session = min(session_minutes, remaining)
        if remaining - actual_session < 15 and remaining > actual_session:
            actual_session = remaining

        session_end = current + timedelta(minutes=actual_session)
        reason = smart_reason(subject, goal, worries, energy_level, index)
        blocks.append(StudyBlock(current, session_end, subject, "study", reason))

        current = session_end
        remaining -= actual_session
        index += 1

        if remaining >= break_minutes + 20:
            break_end = current + timedelta(minutes=break_minutes)
            blocks.append(
                StudyBlock(
                    current,
                    break_end,
                    "Brain reset",
                    "break",
                    "Stand up, drink water, and keep your phone away.",
                )
            )
            current = break_end
            remaining -= break_minutes

    insights = build_insights(
        name,
        morning,
        afternoon,
        evening,
        total_minutes,
        energy_level,
        ranked_subjects,
        goal,
        worries,
    )
    return blocks, insights


def smart_reason(subject, goal, worries, energy_level, index):
    if subject.lower() in goal.lower():
        return "Placed early because it is directly connected to your main goal."
    if subject.lower() in worries.lower():
        return "Prioritized because you marked it as a worry point."
    if energy_level == "high" and index == 0:
        return "Your energy looks strong, so the first deep-focus block goes here."
    if energy_level == "low":
        return "Shorter focused work keeps progress realistic when energy is low."
    return "Balanced rotation keeps your brain fresh and avoids overloading one subject."


def build_insights(name, morning, afternoon, evening, total_minutes, energy_level, ranked_subjects, goal, worries):
    first_subject = ranked_subjects[0] if ranked_subjects else "your hardest subject"
    day_load = "balanced"
    all_activities = f"{morning} {afternoon} {evening}".lower()
    if any(word in all_activities for word in ["school", "training", "work", "exam", "course"]):
        day_load = "busy"
    if any(word in all_activities for word in ["rest", "free", "relax"]):
        day_load = "lighter"

    insights = [
        f"Hello {name or 'student'}, I found {total_minutes} minutes of usable study time.",
        f"Your day looks {day_load}, so the plan avoids unrealistic marathon sessions.",
        f"Detected energy level: {energy_level}. Session length was adjusted automatically.",
        f"Start with {first_subject}; it has the highest smart priority for today.",
        f"Main goal: {goal or 'not specified'}",
    ]

    if worries.strip():
        insights.append(f"Risk area noticed: {worries}. I gave it extra priority.")
    else:
        insights.append("No worry area was added, so subjects are balanced by rotation.")

    return insights


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return []


def save_history(items):
    with HISTORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(items, file, indent=2)


def add_history_record(record):
    history = load_history()
    history.append(record)
    save_history(history)


def weekly_summary():
    history = load_history()
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_items = [
        item for item in history
        if date.fromisoformat(item["date"]) >= week_start
    ]
    study_items = [item for item in week_items if item["type"] in ("study", "setup")]
    completed = [item for item in study_items if item["status"] == "completed"]
    skipped = [item for item in study_items if item["status"] == "skipped"]
    breaks = [item for item in week_items if item["type"] == "break"]

    total = len(study_items)
    rate = round((len(completed) / total) * 100) if total else 0
    if rate >= 90:
        level = "Excellent"
    elif rate >= 75:
        level = "Very good"
    elif rate >= 55:
        level = "Good"
    else:
        level = "Needs improvement"

    return {
        "week_start": week_start.isoformat(),
        "planned": total,
        "completed": len(completed),
        "skipped": len(skipped),
        "breaks": len(breaks),
        "rate": rate,
        "level": level,
        "items": week_items,
    }


class StudentDailyLife(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Student Daily Life")
        self.geometry("1060x720")
        self.minsize(940, 620)
        self.configure(bg="#eef3f8")
        self.current_page = 0
        self.pages = []
        self.current_blocks = []
        self.current_insights = []
        self.current_block_index = 0
        self.current_session_id = None
        self.current_energy_level = "medium"
        self.study_running = False
        self.block_remaining_seconds = 0
        self.countdown_job = None
        self.exercise_job = None
        self.notifications = []
        self.create_style()
        self.create_layout()
        self.show_page(0)

    def create_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef3f8")
        style.configure("Panel.TFrame", background="#ffffff", relief="flat")
        style.configure("TLabel", background="#eef3f8", foreground="#1d2433", font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background="#ffffff", foreground="#1d2433", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#eef3f8", foreground="#111827", font=("Segoe UI", 24, "bold"))
        style.configure("Subtitle.TLabel", background="#eef3f8", foreground="#566174", font=("Segoe UI", 10))
        style.configure("Hero.TLabel", background="#ffffff", foreground="#0f172a", font=("Segoe UI", 24, "bold"))
        style.configure("Section.TLabel", background="#ffffff", foreground="#111827", font=("Segoe UI", 15, "bold"))
        style.configure("Hint.TLabel", background="#ffffff", foreground="#64748b", font=("Segoe UI", 10))
        style.configure("Step.TLabel", background="#eef3f8", foreground="#64748b", font=("Segoe UI", 10, "bold"))
        style.configure("ActiveStep.TLabel", background="#eef3f8", foreground="#0f766e", font=("Segoe UI", 10, "bold"))
        style.configure("Smart.TButton", font=("Segoe UI", 11, "bold"), padding=10)
        style.configure("Nav.TButton", font=("Segoe UI", 10, "bold"), padding=9)
        style.map(
            "Smart.TButton",
            background=[("active", "#0f766e"), ("!disabled", "#14b8a6")],
            foreground=[("!disabled", "#ffffff")],
        )
        style.configure("TEntry", padding=8)
        style.configure("Treeview", rowheight=34, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def create_layout(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=26, pady=(20, 10))

        ttk.Label(header, text="Student Daily Life", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="A smart multi-step assistant that understands a student's day, then creates a personal study plan.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        self.step_bar = ttk.Frame(self)
        self.step_bar.pack(fill="x", padx=26, pady=(0, 12))
        self.step_labels = []
        for text in ["Start", "Daily Life", "Study Goals", "AI Review", "Plan", "Notifications"]:
            label = ttk.Label(self.step_bar, text=text, style="Step.TLabel")
            label.pack(side="left", padx=(0, 18))
            self.step_labels.append(label)

        self.page_area = ttk.Frame(self)
        self.page_area.pack(fill="both", expand=True, padx=26, pady=(0, 14))
        self.page_area.rowconfigure(0, weight=1)
        self.page_area.columnconfigure(0, weight=1)

        self.nav = ttk.Frame(self)
        self.nav.pack(fill="x", padx=26, pady=(0, 22))
        self.back_button = ttk.Button(self.nav, text="Back", style="Nav.TButton", command=self.previous_page)
        self.next_button = ttk.Button(self.nav, text="Next", style="Smart.TButton", command=self.next_page)
        self.status_label = ttk.Label(self.nav, text="", style="Subtitle.TLabel")
        self.back_button.pack(side="left")
        self.status_label.pack(side="left", padx=18)
        self.next_button.pack(side="right")

        self.create_pages()

    def add_field(self, parent, label, row, default=""):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=(8, 3))
        entry = ttk.Entry(parent)
        entry.grid(row=row + 1, column=0, sticky="ew", pady=(0, 4))
        entry.insert(0, default)
        return entry

    def create_pages(self):
        self.create_welcome_page()
        self.create_daily_page()
        self.create_study_page()
        self.create_review_page()
        self.create_plan_page()
        self.create_notifications_page()

    def make_page(self):
        page = ttk.Frame(self.page_area, style="Panel.TFrame", padding=24)
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        self.pages.append(page)
        return page

    def create_welcome_page(self):
        page = self.make_page()
        ttk.Label(page, text="Build your day like a smart assistant would.", style="Hero.TLabel").grid(
            row=0, column=0, sticky="w", pady=(10, 8)
        )
        ttk.Label(
            page,
            text="Student Daily Life asks simple questions, analyzes your available time, then gives you a realistic schedule.",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w")

        features = ttk.Frame(page, style="Panel.TFrame")
        features.grid(row=2, column=0, sticky="ew", pady=(36, 0))
        features.columnconfigure((0, 1, 2), weight=1)

        cards = [
            ("1", "Daily routine scan", "Morning, afternoon, and evening activities are used to detect how busy your day is."),
            ("2", "Smart priority engine", "The app ranks subjects using your goal, worries, time, and energy level."),
            ("3", "Final study plan", "You get a clean schedule with breaks, reasons, and coach notes."),
        ]
        for column, (number, title, body) in enumerate(cards):
            card = ttk.Frame(features, style="Panel.TFrame", padding=16)
            card.grid(row=0, column=column, sticky="nsew", padx=8)
            ttk.Label(card, text=number, style="Section.TLabel").pack(anchor="w")
            ttk.Label(card, text=title, style="Section.TLabel").pack(anchor="w", pady=(8, 6))
            ttk.Label(card, text=body, style="Hint.TLabel", wraplength=260).pack(anchor="w")

        tk.Button(
            page,
            text="Start Questions",
            command=self.next_page,
            bg="#14b8a6",
            fg="white",
            activebackground="#0f766e",
            activeforeground="white",
            relief="flat",
            padx=22,
            pady=12,
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
        ).grid(row=3, column=0, sticky="w", pady=(34, 0))

    def create_daily_page(self):
        page = self.make_page()
        ttk.Label(page, text="Daily life questions", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(page, text="Tell the assistant what your day usually looks like.", style="Hint.TLabel").grid(
            row=1, column=0, sticky="w", pady=(3, 12)
        )

        self.name_entry = self.add_field(page, "Student name", 2, "Mariam")
        self.morning_entry = self.add_field(page, "What do you do in the morning?", 4, "School, breakfast")
        self.afternoon_entry = self.add_field(page, "What do you do in the afternoon?", 6, "Lunch, homework, rest")
        self.evening_entry = self.add_field(page, "What do you do in the evening?", 8, "Family time")

        time_row = ttk.Frame(page, style="Panel.TFrame")
        time_row.grid(row=10, column=0, sticky="ew", pady=(10, 0))
        time_row.columnconfigure(0, weight=1)
        time_row.columnconfigure(1, weight=1)

        ttk.Label(time_row, text="Free time starts", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(time_row, text="Free time ends", style="Panel.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.start_entry = ttk.Entry(time_row)
        self.end_entry = ttk.Entry(time_row)
        self.start_entry.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        self.end_entry.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(3, 0))
        self.start_entry.insert(0, "16:00")
        self.end_entry.insert(0, "20:00")

        tk.Button(
            page,
            text="Continue to Study Goals",
            command=self.next_page,
            bg="#14b8a6",
            fg="white",
            activebackground="#0f766e",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
        ).grid(row=11, column=0, sticky="w", pady=(24, 0))

    def create_study_page(self):
        page = self.make_page()
        ttk.Label(page, text="Study goals", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(page, text="This page gives the planner enough data to act smart.", style="Hint.TLabel").grid(
            row=1, column=0, sticky="w", pady=(3, 12)
        )

        self.subjects_entry = self.add_field(
            page,
            "Subjects, separated by commas",
            2,
            "Math, Science, English",
        )
        self.goal_entry = self.add_field(page, "Today's main goal", 4, "Finish Math homework")
        self.worries_entry = self.add_field(page, "What feels hard or worrying?", 6, "Math exam")

        ttk.Label(page, text="Energy right now", style="Panel.TLabel").grid(row=8, column=0, sticky="w", pady=(8, 3))
        self.energy_box = ttk.Combobox(page, values=["High and fresh", "Medium", "Low or tired"], state="readonly")
        self.energy_box.grid(row=9, column=0, sticky="ew")
        self.energy_box.current(1)

        ttk.Label(page, text="Learning style", style="Panel.TLabel").grid(row=10, column=0, sticky="w", pady=(8, 3))
        self.style_box = ttk.Combobox(
            page,
            values=["Practice problems", "Reading notes", "Videos and examples", "Mixed"],
            state="readonly",
        )
        self.style_box.grid(row=11, column=0, sticky="ew")
        self.style_box.current(3)

        tk.Button(
            page,
            text="Analyze My Answers",
            command=self.next_page,
            bg="#14b8a6",
            fg="white",
            activebackground="#0f766e",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
        ).grid(row=12, column=0, sticky="w", pady=(24, 0))

    def create_review_page(self):
        page = self.make_page()
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text="AI review", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(page, text="Review your answers before creating the final schedule.", style="Hint.TLabel").grid(
            row=1, column=0, sticky="w", pady=(3, 12)
        )
        self.review_text = tk.Text(
            page,
            wrap="word",
            font=("Segoe UI", 11),
            bg="#f8fafc",
            fg="#0f172a",
            relief="flat",
            padx=14,
            pady=14,
            height=18,
        )
        self.review_text.grid(row=2, column=0, sticky="nsew")
        self.review_text.configure(state="disabled")

        tk.Button(
            page,
            text="Create Final Schedule",
            command=self.next_page,
            bg="#14b8a6",
            fg="white",
            activebackground="#0f766e",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
        ).grid(row=3, column=0, sticky="w", pady=(14, 0))

    def create_plan_page(self):
        page = self.make_page()
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text="Your smart study schedule", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.plan_hint = ttk.Label(page, text="", style="Hint.TLabel")
        self.plan_hint.grid(row=1, column=0, sticky="w", pady=(3, 12))

        columns = ("time", "type", "task", "reason")
        self.plan_table = ttk.Treeview(page, columns=columns, show="headings")
        self.plan_table.heading("time", text="Time")
        self.plan_table.heading("type", text="Type")
        self.plan_table.heading("task", text="Task")
        self.plan_table.heading("reason", text="Smart reason")
        self.plan_table.column("time", width=130, stretch=False)
        self.plan_table.column("type", width=90, stretch=False)
        self.plan_table.column("task", width=170, stretch=False)
        self.plan_table.column("reason", width=520)
        self.plan_table.grid(row=2, column=0, sticky="nsew")

        mode_panel = ttk.Frame(page, style="Panel.TFrame")
        mode_panel.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        mode_panel.columnconfigure(0, weight=1)
        mode_panel.columnconfigure(1, weight=1)
        mode_panel.columnconfigure(2, weight=1)

        self.study_status_label = ttk.Label(
            mode_panel,
            text="Study Mode is waiting. Press Start when you are ready.",
            style="Panel.TLabel",
        )
        self.study_status_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.timer_label = ttk.Label(mode_panel, text="00:00", style="Section.TLabel")
        self.timer_label.grid(row=1, column=0, sticky="w")

        tk.Button(
            mode_panel,
            text="Start Study Mode",
            command=self.start_study_mode,
            bg="#14b8a6",
            fg="white",
            activebackground="#0f766e",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=9,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).grid(row=1, column=1, sticky="ew", padx=8)
        tk.Button(
            mode_panel,
            text="Done Current",
            command=lambda: self.finish_current_block("completed"),
            bg="#2563eb",
            fg="white",
            activebackground="#1d4ed8",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=9,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).grid(row=1, column=2, sticky="ew", padx=(8, 0))
        tk.Button(
            mode_panel,
            text="Skip Current",
            command=lambda: self.finish_current_block("skipped"),
            bg="#f97316",
            fg="white",
            activebackground="#ea580c",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=9,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).grid(row=2, column=1, sticky="ew", padx=8, pady=(8, 0))
        tk.Button(
            mode_panel,
            text="Weekly Report",
            command=self.show_weekly_report,
            bg="#334155",
            fg="white",
            activebackground="#1e293b",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=9,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).grid(row=2, column=2, sticky="ew", padx=(8, 0), pady=(8, 0))
        tk.Button(
            mode_panel,
            text="Open Notifications",
            command=lambda: self.show_page(5),
            bg="#7c3aed",
            fg="white",
            activebackground="#6d28d9",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=9,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).grid(row=2, column=0, sticky="ew", pady=(8, 0))

        self.notes_text = tk.Text(
            page,
            wrap="word",
            font=("Segoe UI", 10),
            bg="#f8fafc",
            fg="#0f172a",
            relief="flat",
            height=6,
            padx=12,
            pady=10,
        )
        self.notes_text.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.notes_text.configure(state="disabled")

        tk.Button(
            page,
            text="Make Another Plan",
            command=self.restart,
            bg="#334155",
            fg="white",
            activebackground="#1e293b",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).grid(row=5, column=0, sticky="w", pady=(12, 0))

    def create_notifications_page(self):
        page = self.make_page()
        page.rowconfigure(3, weight=1)
        page.columnconfigure(0, weight=1)
        ttk.Label(page, text="Smart Notification Center", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            page,
            text="All reminders live here, so Study Mode can guide you without crowding the app.",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 12))

        self.notification_banner = ttk.Label(
            page,
            text="No notifications yet. Start Study Mode to activate smart reminders.",
            style="Hint.TLabel",
            wraplength=860,
        )
        self.notification_banner.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        columns = ("time", "kind", "message")
        self.notification_table = ttk.Treeview(page, columns=columns, show="headings")
        self.notification_table.heading("time", text="Time")
        self.notification_table.heading("kind", text="Type")
        self.notification_table.heading("message", text="Smart notification")
        self.notification_table.column("time", width=100, stretch=False)
        self.notification_table.column("kind", width=110, stretch=False)
        self.notification_table.column("message", width=700)
        self.notification_table.grid(row=3, column=0, sticky="nsew")

        action_row = ttk.Frame(page, style="Panel.TFrame")
        action_row.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        tk.Button(
            action_row,
            text="Back to Plan",
            command=lambda: self.show_page(4),
            bg="#14b8a6",
            fg="white",
            activebackground="#0f766e",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).pack(side="left")
        tk.Button(
            action_row,
            text="Clear Notifications",
            command=self.clear_notifications,
            bg="#334155",
            fg="white",
            activebackground="#1e293b",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        ).pack(side="left", padx=(10, 0))

    def collect_inputs(self):
        name = self.name_entry.get().strip()
        morning = self.morning_entry.get().strip()
        afternoon = self.afternoon_entry.get().strip()
        evening = self.evening_entry.get().strip()
        free_start = self.start_entry.get().strip()
        free_end = self.end_entry.get().strip()
        subjects = split_items(self.subjects_entry.get())
        goal = self.goal_entry.get().strip()
        worries = self.worries_entry.get().strip()
        energy = self.energy_box.get()

        if not name:
            raise ValueError("Please enter the student's name.")
        if not subjects:
            raise ValueError("Please add at least one subject.")
        parse_time(free_start)
        parse_time(free_end)

        return {
            "name": name,
            "morning": morning,
            "afternoon": afternoon,
            "evening": evening,
            "free_start": free_start,
            "free_end": free_end,
            "subjects": subjects,
            "goal": goal,
            "worries": worries,
            "energy": energy,
            "learning_style": self.style_box.get(),
        }

    def validate_current_page(self):
        try:
            if self.current_page == 1:
                if not self.name_entry.get().strip():
                    raise ValueError("Please enter the student's name.")
                parse_time(self.start_entry.get())
                parse_time(self.end_entry.get())
            if self.current_page == 2:
                if not split_items(self.subjects_entry.get()):
                    raise ValueError("Please add at least one subject.")
        except ValueError as error:
            messagebox.showerror("Check your inputs", str(error))
            return False
        return True

    def next_page(self):
        if self.current_page == 5:
            self.show_page(4)
            return
        if self.current_page == 4:
            self.restart()
            return
        if not self.validate_current_page():
            return
        if self.current_page == 2:
            self.update_review()
        if self.current_page == 3:
            self.generate()
        self.show_page(self.current_page + 1)

    def previous_page(self):
        if self.current_page > 0:
            self.show_page(self.current_page - 1)

    def show_page(self, index):
        self.current_page = index
        self.pages[index].tkraise()

        for step_index, label in enumerate(self.step_labels):
            label.configure(style="ActiveStep.TLabel" if step_index == index else "Step.TLabel")

        self.back_button.configure(state="disabled" if index == 0 else "normal")
        if index == 3:
            self.next_button.configure(text="Create Schedule")
        elif index == 4:
            self.next_button.configure(text="Start Again")
        elif index == 5:
            self.next_button.configure(text="Back to Plan")
        else:
            self.next_button.configure(text="Next")

        self.status_label.configure(text=f"Step {index + 1} of {len(self.pages)}")

    def update_review(self):
        try:
            data = self.collect_inputs()
        except ValueError as error:
            messagebox.showerror("Check your inputs", str(error))
            return

        total = minutes_between(parse_time(data["free_start"]), parse_time(data["free_end"]))
        preview = [
            "Student Daily Life AI Review",
            "-" * 42,
            f"Student: {data['name']}",
            f"Free time: {data['free_start']} to {data['free_end']} ({total} minutes)",
            f"Subjects: {', '.join(data['subjects'])}",
            f"Main goal: {data['goal'] or 'Not specified'}",
            f"Hard area: {data['worries'] or 'None'}",
            f"Energy: {data['energy']}",
            f"Learning style: {data['learning_style']}",
            "",
            "Smart prediction:",
            "The final page will rank your subjects, add breaks, and explain why each block was chosen.",
        ]
        self.review_text.configure(state="normal")
        self.review_text.delete("1.0", "end")
        self.review_text.insert("end", "\n".join(preview))
        self.review_text.configure(state="disabled")

    def restart(self):
        self.stop_timers()
        self.study_running = False
        self.current_block_index = 0
        self.show_page(0)

    def generate(self):
        try:
            data = self.collect_inputs()
            blocks, insights = smart_plan(
                data["name"],
                data["morning"],
                data["afternoon"],
                data["evening"],
                data["free_start"],
                data["free_end"],
                data["subjects"],
                data["goal"],
                data["worries"],
                data["energy"],
            )
        except ValueError as error:
            messagebox.showerror("Check your inputs", str(error))
            return

        self.current_blocks = blocks
        self.current_insights = insights
        self.current_block_index = 0
        self.current_session_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self.current_energy_level = detect_energy_level(data["energy"])
        self.study_running = False
        self.show_plan(blocks, insights, data["learning_style"])

    def show_plan(self, blocks, insights, learning_style):
        for item in self.plan_table.get_children():
            self.plan_table.delete(item)

        for block in blocks:
            self.plan_table.insert(
                "",
                "end",
                values=(
                    f"{format_time(block.start)} - {format_time(block.end)}",
                    block.block_type.upper(),
                    block.title,
                    block.reason,
                ),
            )

        self.plan_hint.configure(text="Final schedule generated by Student Daily Life.")
        self.study_status_label.configure(text="Study Mode is waiting. Press Start when you are ready.")
        self.timer_label.configure(text="00:00")
        self.add_notification(
            "SYSTEM",
            "Your plan is ready. Start Study Mode when you want the assistant to guide you block by block.",
            ring=False,
        )

        notes = [
            "AI diagnosis:",
            *[f"* {insight}" for insight in insights],
            "",
            "Coach notes:",
            "* Before every study block, write one tiny target.",
            "* After every block, rate your focus from 1 to 5.",
            f"* Learning style selected: {learning_style}. Use it inside each study block.",
            "* If focus is under 3 twice, switch to a lighter subject for one block.",
        ]
        self.notes_text.configure(state="normal")
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("end", "\n".join(notes))
        self.notes_text.configure(state="disabled")

    def start_study_mode(self):
        if not self.current_blocks:
            messagebox.showinfo("No plan yet", "Create a schedule first, then start Study Mode.")
            return
        if self.study_running:
            messagebox.showinfo("Already running", "Study Mode is already running.")
            return

        self.study_running = True
        self.current_block_index = 0
        self.current_session_id = self.current_session_id or datetime.now().strftime("%Y%m%d%H%M%S")
        self.start_current_block()

    def start_current_block(self):
        self.stop_timers()
        if self.current_block_index >= len(self.current_blocks):
            self.finish_session()
            return

        block = self.current_blocks[self.current_block_index]
        duration_minutes = max(1, minutes_between(block.start, block.end))
        self.block_remaining_seconds = duration_minutes * 60
        self.highlight_current_block()

        if block.block_type == "break":
            title = "Break time"
            body = "Break time has started. Stand up, breathe, and reset your brain."
            kind = "BREAK"
        elif block.block_type == "setup":
            title = "Warm-up time"
            body = "Write your exact goal, clear your desk, and get ready."
            kind = "SYSTEM"
        else:
            title = f"Study {block.title} now"
            body = f"Time to study {block.title}. Focus on one tiny target."
            kind = "STUDY"

        self.study_status_label.configure(text=f"Now: {block.title} ({block.block_type})")
        self.show_notification(title, body, kind)
        self.tick_timer()

        if block.block_type == "study" and duration_minutes > EXERCISE_REMINDER_MINUTES:
            self.exercise_job = self.after(EXERCISE_REMINDER_MINUTES * MINUTE_MS, self.show_exercise_reminder)

    def tick_timer(self):
        if not self.study_running:
            return

        minutes = self.block_remaining_seconds // 60
        seconds = self.block_remaining_seconds % 60
        self.timer_label.configure(text=f"{minutes:02d}:{seconds:02d}")

        if self.block_remaining_seconds <= 0:
            self.finish_current_block("completed")
            return

        self.block_remaining_seconds -= 1
        self.countdown_job = self.after(1000, self.tick_timer)

    def show_exercise_reminder(self):
        if not self.study_running or self.current_block_index >= len(self.current_blocks):
            return

        block = self.current_blocks[self.current_block_index]
        if block.block_type != "study":
            return

        self.show_notification("Move reminder", smart_movement_for_energy(self.current_energy_level), "MOVE")
        if self.block_remaining_seconds > EXERCISE_REMINDER_MINUTES * 60:
            self.exercise_job = self.after(EXERCISE_REMINDER_MINUTES * MINUTE_MS, self.show_exercise_reminder)

    def finish_current_block(self, status):
        if not self.study_running or self.current_block_index >= len(self.current_blocks):
            return

        block = self.current_blocks[self.current_block_index]
        add_history_record(
            {
                "date": date.today().isoformat(),
                "session_id": self.current_session_id,
                "title": block.title,
                "type": block.block_type,
                "status": status,
                "planned_start": format_time(block.start),
                "planned_end": format_time(block.end),
                "finished_at": datetime.now().strftime("%H:%M"),
            }
        )

        self.current_block_index += 1
        self.start_current_block()

    def finish_session(self):
        self.stop_timers()
        self.study_running = False
        self.study_status_label.configure(text="Session finished. Great work. Open Weekly Report to see your progress.")
        self.timer_label.configure(text="Done")
        self.show_notification("Session complete", "You finished today's Study Mode. Check your weekly report.", "SYSTEM")

    def stop_timers(self):
        if self.countdown_job is not None:
            self.after_cancel(self.countdown_job)
            self.countdown_job = None
        if self.exercise_job is not None:
            self.after_cancel(self.exercise_job)
            self.exercise_job = None

    def highlight_current_block(self):
        for index, item in enumerate(self.plan_table.get_children()):
            self.plan_table.selection_remove(item)
            if index == self.current_block_index:
                self.plan_table.selection_set(item)
                self.plan_table.see(item)

    def show_notification(self, title, message, kind="SYSTEM"):
        smart_message = self.make_smart_notification(title, message, kind)
        self.add_notification(kind, smart_message)

    def make_smart_notification(self, title, message, kind):
        prefix = {
            "STUDY": "Focus cue",
            "BREAK": "Recovery cue",
            "MOVE": "Body reset",
            "SYSTEM": "Assistant",
        }.get(kind, "Assistant")
        return f"{prefix}: {title}. {message}"

    def add_notification(self, kind, message, ring=True):
        item = {
            "time": datetime.now().strftime("%H:%M"),
            "kind": kind,
            "message": message,
        }
        self.notifications.append(item)
        if len(self.notifications) > 50:
            self.notifications = self.notifications[-50:]
        if ring:
            self.bell()
        self.refresh_notifications()

    def refresh_notifications(self):
        if not hasattr(self, "notification_table"):
            return

        for row in self.notification_table.get_children():
            self.notification_table.delete(row)
        for item in reversed(self.notifications):
            self.notification_table.insert("", "end", values=(item["time"], item["kind"], item["message"]))

        latest = self.notifications[-1]["message"] if self.notifications else "No notifications yet."
        self.notification_banner.configure(text=latest)
        if hasattr(self, "plan_hint"):
            self.plan_hint.configure(text=f"Latest smart notification: {latest}")

    def clear_notifications(self):
        self.notifications = []
        self.refresh_notifications()
        self.notification_banner.configure(text="Notifications cleared. Study Mode will add new smart reminders here.")

    def show_weekly_report(self):
        report = weekly_summary()
        done_titles = [
            item["title"] for item in report["items"]
            if item["status"] == "completed" and item["type"] in ("study", "setup")
        ]
        skipped_titles = [
            item["title"] for item in report["items"]
            if item["status"] == "skipped" and item["type"] in ("study", "setup")
        ]

        done_text = ", ".join(done_titles[-8:]) if done_titles else "Nothing completed yet."
        skipped_text = ", ".join(skipped_titles[-8:]) if skipped_titles else "Nothing skipped yet."
        message = (
            f"Week starting: {report['week_start']}\n\n"
            f"Completed: {report['completed']} / {report['planned']}\n"
            f"Skipped: {report['skipped']}\n"
            f"Breaks taken: {report['breaks']}\n"
            f"Commitment rate: {report['rate']}%\n"
            f"Level: {report['level']}\n\n"
            f"You did: {done_text}\n\n"
            f"You missed: {skipped_text}"
        )
        messagebox.showinfo("Weekly Report", message)


def local_ip_address():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
        sock.close()
        return address
    except OSError:
        return "127.0.0.1"


def run_web_server():
    folder = Path(__file__).parent.resolve()
    index_file = folder / "index.html"
    fallback_file = folder / "student_daily_life_web.html"

    if not index_file.exists() and fallback_file.exists():
        index_file.write_text(fallback_file.read_text(encoding="utf-8"), encoding="utf-8")

    if not index_file.exists():
        app = StudentDailyLife()
        app.mainloop()
        return

    handler = partial(SimpleHTTPRequestHandler, directory=str(folder))
    ip_address = local_ip_address()

    for port in range(8000, 8010):
        try:
            with socketserver.ThreadingTCPServer(("0.0.0.0", port), handler) as server:
                computer_url = f"http://localhost:{port}/"
                phone_url = f"http://{ip_address}:{port}/"
                print("\nStudent Daily Life is running.")
                print(f"Computer link: {computer_url}")
                print(f"Phone link on the same Wi-Fi: {phone_url}")
                print("Keep this window open. Press Ctrl+C to stop the server.\n")
                webbrowser.open(computer_url)
                server.serve_forever()
                return
        except OSError:
            continue

    print("Could not start the local web server. Try closing apps using ports 8000-8009.")


if __name__ == "__main__":
    run_web_server()
