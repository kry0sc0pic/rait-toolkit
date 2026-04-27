import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Download, FileText, GraduationCap, LogOut } from "lucide-react";
import "./styles.css";

type Credentials = {
  username: string;
  password: string;
};

type Course = {
  id: string;
  name: string;
  url: string;
};

type AttendanceSubject = {
  subject: string;
  total_classes: number | string;
  present: number | string;
  absent: number | string;
  percentage: number | string;
};

type Attendance = {
  batch?: string;
  semester?: string;
  subjects?: AttendanceSubject[];
};

type Material = {
  name: string;
  type: string;
  activity_url: string;
};

type CourseData = {
  content: Section[] | string;
  assignments: Assignment[] | string;
  grades: Grades | string;
  announcements: Announcement[] | string;
  materials: { course_name: string; materials: Material[] } | string;
};

type Section = {
  section_name: string;
  activities: { name: string; type: string; url: string }[];
};

type Assignment = {
  name: string;
  due_date?: string | null;
  submission_status?: string | null;
  grading_status?: string | null;
  grade?: string | null;
};

type Grades = {
  grade_items: {
    name: string;
    grade?: string | null;
    range?: string | null;
    percentage?: string | null;
    feedback?: string | null;
  }[];
  course_total?: { grade?: string | null; percentage?: string | null } | null;
};

type Announcement = {
  title: string;
  author?: string | null;
  date?: string | null;
  content?: string | null;
};

type DashboardData = {
  courses: Course[];
  current_courses: Course[];
  attendance: Attendance | string;
};

type CurrentSubjectCourse = {
  course: Course;
  attendance: AttendanceSubject;
};

const STORAGE_KEY = "lms-buddy-credentials";
const JOURNAL_PROFILE_KEY = "lms-buddy-journal-profile";

type JournalProfile = {
  name: string;
  usn: string;
  roll: string;
  batch: string;
};

function loadSavedCredentials(): Credentials {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : { username: "", password: "" };
  } catch {
    return { username: "", password: "" };
  }
}

function loadJournalProfile(): JournalProfile {
  try {
    const raw = localStorage.getItem(JOURNAL_PROFILE_KEY);
    return raw ? JSON.parse(raw) : { name: "", usn: "", roll: "", batch: "" };
  } catch {
    return { name: "", usn: "", roll: "", batch: "" };
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || "Request failed.");
  }
  return payload as T;
}

function avgAttendance(attendance: Attendance | string | undefined): number {
  if (!attendance || typeof attendance === "string") return 0;
  const active = (attendance.subjects || []).filter(
    (subject) => typeof subject.total_classes === "number" && subject.total_classes > 0,
  );
  const present = active.reduce((sum, subject) => sum + Number(subject.present || 0), 0);
  const total = active.reduce((sum, subject) => sum + Number(subject.total_classes || 0), 0);
  return total ? Math.round((present / total) * 100) : 0;
}

function normalizeName(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function acronym(value: string): string {
  return value
    .split(/[^a-zA-Z0-9]+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .toLowerCase();
}

function matchCourseForSubject(subject: AttendanceSubject, courses: Course[], fallback?: Course): Course | null {
  const normalizedSubject = normalizeName(subject.subject);
  const subjectAcronym = acronym(subject.subject);
  const match = courses.find((course) => {
    const normalizedCourse = normalizeName(course.name);
    return (
      normalizedCourse.includes(normalizedSubject) ||
      normalizedSubject.includes(normalizedCourse) ||
      acronym(course.name) === subjectAcronym
    );
  });
  return match || fallback || null;
}

function attendancePercent(subject?: AttendanceSubject): number {
  return typeof subject?.percentage === "number" ? subject.percentage : 0;
}

function classesLabel(subject: AttendanceSubject): string {
  if (typeof subject.total_classes !== "number" || subject.total_classes <= 0) {
    return "";
  }
  return `${subject.present}/${subject.total_classes} classes`;
}

export function App() {
  const [credentials, setCredentials] = useState<Credentials>(() => loadSavedCredentials());
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [selectedCourse, setSelectedCourse] = useState<Course | null>(null);
  const [courseData, setCourseData] = useState<CourseData | null>(null);
  const [view, setView] = useState<"courses" | "journal" | "general">("courses");
  const [journalProfile, setJournalProfile] = useState<JournalProfile>(() => loadJournalProfile());
  const [journalSubject, setJournalSubject] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);
  const [bulkDownloading, setBulkDownloading] = useState(false);
  const bulkCancelRef = useRef(false);
  const activeDownloadControllerRef = useRef<AbortController | null>(null);

  const hasSavedCredentials = credentials.username && credentials.password;

  useEffect(() => {
    if (hasSavedCredentials) {
      void loadDashboard(credentials);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(JOURNAL_PROFILE_KEY, JSON.stringify(journalProfile));
  }, [journalProfile]);

  async function loadDashboard(nextCredentials = credentials) {
    setLoading(true);
    setError("");
    try {
      const data = await postJson<DashboardData>("/api/dashboard", nextCredentials);
      setDashboard(data);
      setView("courses");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load dashboard.");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await postJson("/api/login", credentials);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(credentials));
      await loadDashboard(credentials);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  }

  async function openCourse(course: Course) {
    setSelectedCourse(course);
    setCourseData(null);
    setLoading(true);
    setError("");
    try {
      const data = await postJson<CourseData>("/api/course", {
        ...credentials,
        course_id: course.id,
      });
      setCourseData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load course.");
    } finally {
      setLoading(false);
    }
  }

  async function downloadMaterial(material: Material, signal?: AbortSignal): Promise<"completed" | "cancelled" | "failed"> {
    setDownloading(material.activity_url);
    setError("");
    try {
      const response = await fetch("/api/download", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...credentials, activity_url: material.activity_url }),
        signal,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.message || "Download failed.");
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
      const filename = match ? decodeURIComponent(match[1]) : `${material.name || "material"}.download`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
      return "completed";
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return "cancelled";
      }
      setError(err instanceof Error ? err.message : "Download failed.");
      return "failed";
    } finally {
      setDownloading(null);
    }
  }

  async function downloadAllMaterials(materials: Material[]) {
    bulkCancelRef.current = false;
    setBulkDownloading(true);
    try {
      for (const material of materials) {
        if (bulkCancelRef.current) break;
        const controller = new AbortController();
        activeDownloadControllerRef.current = controller;
        const result = await downloadMaterial(material, controller.signal);
        activeDownloadControllerRef.current = null;
        if (result === "cancelled" || bulkCancelRef.current) break;
      }
    } finally {
      activeDownloadControllerRef.current = null;
      setBulkDownloading(false);
    }
  }

  function cancelDownloadAll() {
    bulkCancelRef.current = true;
    activeDownloadControllerRef.current?.abort();
    setBulkDownloading(false);
  }

  function logout() {
    localStorage.removeItem(STORAGE_KEY);
    setDashboard(null);
    setSelectedCourse(null);
    setCourseData(null);
    setCredentials({ username: "", password: "" });
  }

  function switchView(nextView: "courses" | "journal" | "general") {
    setSelectedCourse(null);
    setCourseData(null);
    setView(nextView);
  }

  const subjects = typeof dashboard?.attendance === "object" ? dashboard.attendance.subjects || [] : [];
  const currentSubjectCourses = useMemo(() => {
    const courses = dashboard?.courses || [];
    const fallbackCourses = dashboard?.current_courses || [];
    return subjects
      .map((subject, index) => {
        const course = matchCourseForSubject(subject, courses, fallbackCourses[index]);
        return course ? { course, attendance: subject } : null;
      })
      .filter((item): item is CurrentSubjectCourse => Boolean(item));
  }, [dashboard, subjects]);

  const olderCourses = useMemo(() => {
    const currentIds = new Set(currentSubjectCourses.map((item) => item.course.id));
    return (dashboard?.courses || []).filter((course) => !currentIds.has(course.id));
  }, [dashboard, currentSubjectCourses]);

  if (!dashboard) {
    return (
      <main className="login-page">
        <section className="login-card">
          <p className="eyebrow">MyDy helper</p>
          <h1>LMS Buddy</h1>
          <p className="muted">A clean web dashboard for attendance, courses, grades, and materials.</p>
          <form onSubmit={handleLogin} className="login-form">
            <input
              placeholder="Username / Email"
              value={credentials.username}
              onChange={(event) => setCredentials({ ...credentials, username: event.target.value })}
              autoComplete="username"
            />
            <input
              placeholder="Password"
              type="password"
              value={credentials.password}
              onChange={(event) => setCredentials({ ...credentials, password: event.target.value })}
              autoComplete="current-password"
            />
            {error && <p className="error">{error}</p>}
            <button className="primary-button" disabled={loading}>
              {loading ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  const average = avgAttendance(dashboard.attendance);

  return (
    <main className="app-shell">
      <nav className="top-nav">
        <div>
          <p className="eyebrow">LMS Buddy</p>
          <strong>Study space</strong>
        </div>
        <div className="nav-tabs">
          <button className={view === "courses" ? "active" : ""} onClick={() => switchView("courses")}>
            Courses
          </button>
          <button className={view === "journal" ? "active" : ""} onClick={() => switchView("journal")}>
            Lab / Journal
          </button>
          <button className={view === "general" ? "active" : ""} onClick={() => switchView("general")}>
            Tools
          </button>
        </div>
        <button className="ghost-button" onClick={logout}>
          <LogOut size={16} /> Logout
        </button>
      </nav>

      <section className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">{typeof dashboard.attendance !== "string" && dashboard.attendance.semester}</p>
            <h1>{selectedCourse ? selectedCourse.name : view === "courses" ? "Courses" : view === "journal" ? "Lab / Journal" : "Tools"}</h1>
          </div>
          <div className="status-pill">{loading ? "Syncing" : "Ready"}</div>
        </header>

        {error && <p className="error banner">{error}</p>}

        {selectedCourse ? (
          <CourseDetail
            course={selectedCourse}
            data={courseData}
            loading={loading}
            downloading={downloading}
            bulkDownloading={bulkDownloading}
            onBack={() => {
              setSelectedCourse(null);
              setCourseData(null);
            }}
            onDownload={downloadMaterial}
            onDownloadAll={downloadAllMaterials}
            onCancelDownloadAll={cancelDownloadAll}
          />
        ) : view === "courses" ? (
          <CoursesPage
            currentCourses={currentSubjectCourses}
            olderCourses={olderCourses}
            average={average}
            onOpenCourse={openCourse}
          />
        ) : view === "journal" ? (
          <JournalUtils
            currentCourses={currentSubjectCourses}
            profile={journalProfile}
            subjectId={journalSubject}
            setProfile={setJournalProfile}
            setSubjectId={setJournalSubject}
          />
        ) : (
          <GeneralUtils currentCourses={currentSubjectCourses} />
        )}
        <AppFooter />
      </section>
    </main>
  );
}

function AppFooter() {
  return (
    <footer className="app-footer">
      Built by{" "}
      <a href="https://github.com/Deeptanshuu" target="_blank" rel="noreferrer">
        Deeptanshu
      </a>
      ,{" "}
      <a href="https://github.com/kry0sc0pic" target="_blank" rel="noreferrer">
        Krishaay
      </a>
      ,{" "}
      <a href="https://claude.ai" target="_blank" rel="noreferrer">
        Claude Code
      </a>{" "}
      and{" "}
      <a href="https://cursor.com/agents" target="_blank" rel="noreferrer">
        Cursor
      </a>
      . Source code @{" "}
      <a href="https://github.com/kry0sc0pic/mydy-lms-scraper" target="_blank" rel="noreferrer">
        GitHub
      </a>
    </footer>
  );
}

function CoursesPage({
  currentCourses,
  olderCourses,
  average,
  onOpenCourse,
}: {
  currentCourses: CurrentSubjectCourse[];
  olderCourses: Course[];
  average: number;
  onOpenCourse: (course: Course) => void;
}) {
  return (
    <>
      <section className="hero-panel panel">
        <div>
          <p className="eyebrow">Current page</p>
          <h2>Courses and attendance</h2>
          <p className="muted">Open current courses, check attendance, or browse older subjects.</p>
        </div>
        <CircularDial value={average} />
      </section>
      <section className="panel">
        <div className="section-title">
          <h2>Current Courses</h2>
          <span>{currentCourses.length} active courses</span>
        </div>
        <div className="subject-grid hitrate-grid">
          {currentCourses.length ? (
            currentCourses.map((item) => <SubjectCard key={`${item.course.id}-${item.attendance.subject}`} item={item} onOpenCourse={onOpenCourse} />)
          ) : (
            <p className="muted">No attendance subjects found.</p>
          )}
        </div>
      </section>
      <details className="panel accordion">
        <summary>Older subjects</summary>
        <div className="course-grid">
          {olderCourses.map((course) => (
            <button className="course-card" key={course.id} onClick={() => onOpenCourse(course)}>
              <span>{course.name}</span>
            </button>
          ))}
        </div>
      </details>
    </>
  );
}

function CircularDial({ value }: { value: number }) {
  return (
    <div className="dial" style={{ "--pct": `${Math.min(100, Math.max(0, value))}%` } as React.CSSProperties}>
      <div>
        <strong>{value}%</strong>
      </div>
    </div>
  );
}

function SubjectCard({ item, onOpenCourse }: { item: CurrentSubjectCourse; onOpenCourse: (course: Course) => void }) {
  const pct = attendancePercent(item.attendance);
  const classText = classesLabel(item.attendance);
  return (
    <button className="subject-card" onClick={() => onOpenCourse(item.course)}>
      <CircularDial value={Math.round(pct)} />
      <div>
        <strong>{item.attendance.subject}</strong>
        {classText && <span>{classText}</span>}
        {normalizeName(item.course.name) !== normalizeName(item.attendance.subject) && <small>{item.course.name}</small>}
      </div>
    </button>
  );
}

function JournalUtils({
  currentCourses,
  profile,
  subjectId,
  setProfile,
  setSubjectId,
}: {
  currentCourses: CurrentSubjectCourse[];
  profile: JournalProfile;
  subjectId: string;
  setProfile: (value: JournalProfile) => void;
  setSubjectId: (value: string) => void;
}) {
  const updateProfile = (key: keyof JournalProfile, value: string) => {
    setProfile({ ...profile, [key]: value });
  };

  return (
    <>
      <section className="panel utility-panel">
        <div className="section-title">
          <h2>Student details</h2>
          <span>Saved locally for lab and journal tools</span>
        </div>
        <div className="form-grid">
          <input placeholder="Name" value={profile.name} onChange={(event) => updateProfile("name", event.target.value)} />
          <input placeholder="USN number" value={profile.usn} onChange={(event) => updateProfile("usn", event.target.value)} />
          <input placeholder="Roll number" value={profile.roll} onChange={(event) => updateProfile("roll", event.target.value)} />
          <input placeholder="Batch / Course" value={profile.batch} onChange={(event) => updateProfile("batch", event.target.value)} />
        </div>
      </section>
      <section className="panel utility-panel">
        <div className="section-title">
          <h2>Cover page generator</h2>
          <span>Uses your Word document template for PDF generation</span>
        </div>
        <p className="muted">Generate cover sheets from a DOCX template, then export them as PDFs.</p>
        <div className="utility-actions">
          <button className="download-button" type="button">
            <FileText size={15} /> Generate CO/PO cover sheet
          </button>
          <button className="download-button" type="button">
            <FileText size={15} /> Generate plain cover sheet
          </button>
        </div>
      </section>
      <section className="panel utility-panel">
        <div className="section-title">
          <h2>Writeup generator</h2>
          <span>Coming soon</span>
        </div>
        <p className="muted">Use AI to generate journal-ready writeups and code from experiment aims.</p>
        <label className="field-label">
          Select subject <span>BETA Feature</span>
          <select value={subjectId} onChange={(event) => setSubjectId(event.target.value)}>
            <option value="">Choose current subject</option>
            {currentCourses.map((item) => (
              <option key={item.course.id} value={item.course.id}>
                {item.attendance.subject}
              </option>
            ))}
          </select>
        </label>
        <button className="primary-button subtle-primary" type="button" disabled>
          Create journal writeups <span>[experimental]</span>
        </button>
      </section>
    </>
  );
}

function GeneralUtils({ currentCourses }: { currentCourses: CurrentSubjectCourse[] }) {
  const [animatingCourseId, setAnimatingCourseId] = useState<string | null>(null);

  const playAnimation = (courseId: string) => {
    setAnimatingCourseId(null);
    window.setTimeout(() => setAnimatingCourseId(courseId), 0);
    window.setTimeout(() => setAnimatingCourseId(null), 1100);
  };

  return (
    <section className={`panel hitrate-panel ${animatingCourseId ? "hitrate-panel--active" : ""}`}>
      <div className="section-title">
        <h2>Hitrate Maxxer</h2>
        <span>Current courses only</span>
      </div>
      <p className="muted">
        Attempts to open all LMS resources to maximize LMS activity for submission slips. It may not reach 100% depending on the type of resources uploaded by faculty.
      </p>
      {currentCourses.length ? (
        <div className="subject-grid">
          {currentCourses.map((item) => (
            <article
              className={`utility-course-card hitrate-card ${animatingCourseId === item.course.id ? "hitrate-card--active" : ""}`}
              key={item.course.id}
            >
              <CircularDial value={0} />
              <div>
                <strong>{item.attendance.subject}</strong>
                <small>Hitrate percentage will be populated later.</small>
              </div>
              <button className="hitrate-button" type="button" onClick={() => playAnimation(item.course.id)}>
                Execute maxxing
              </button>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted">No current courses found.</p>
      )}
    </section>
  );
}

function CourseDetail({
  course,
  data,
  loading,
  downloading,
  bulkDownloading,
  onBack,
  onDownload,
  onDownloadAll,
  onCancelDownloadAll,
}: {
  course: Course;
  data: CourseData | null;
  loading: boolean;
  downloading: string | null;
  bulkDownloading: boolean;
  onBack: () => void;
  onDownload: (material: Material) => void;
  onDownloadAll: (materials: Material[]) => void;
  onCancelDownloadAll: () => void;
}) {
  const materials = data && typeof data.materials !== "string" ? data.materials.materials : [];
  return (
    <>
      <button className="back-button" onClick={onBack}>
        Back to courses
      </button>
      <section className="panel course-panel">
        <div className="section-title">
          <h2>{course.name}</h2>
        </div>
        <div className="download-note">
          <GraduationCap size={17} />
          Downloads are proxied through LMS Buddy. Large files may take time or hit Vercel limits.
        </div>
        <div className="download-actions">
          <button
            className={`download-button ${bulkDownloading ? "danger" : ""}`}
            type="button"
            disabled={loading || (!bulkDownloading && !materials.length)}
            onClick={() => (bulkDownloading ? onCancelDownloadAll() : onDownloadAll(materials))}
          >
            <Download size={15} />
            {bulkDownloading ? "Cancel downloads" : "Download all"}
          </button>
        </div>
        <div className="document-table">
          {loading && !data ? (
            <div className="loading-row">
              <span className="spinner" />
              Loading files...
            </div>
          ) : (
            materials.map((material) => (
              <div className="document-row" key={material.activity_url}>
                <div>
                  <strong>{material.name}</strong>
                  <span>{material.type}</span>
                </div>
                <button
                  className="download-button"
                  disabled={bulkDownloading || downloading === material.activity_url}
                  onClick={() => onDownload(material)}
                >
                  <Download size={15} />
                  {downloading === material.activity_url ? "Downloading..." : "Download"}
                </button>
              </div>
            ))
          )}
          {!loading && !materials.length && <p className="muted">No downloadable materials found.</p>}
        </div>
      </section>
    </>
  );
}

const root = document.getElementById("root");

if (root) {
  createRoot(root).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
