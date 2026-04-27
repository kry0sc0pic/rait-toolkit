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

type HitrateCourseResult = {
  success: boolean;
  course_name?: string;
  manual_activities?: number;
  marked?: number;
  skipped?: number;
  failed?: number;
  message?: string;
};

type AppView = "courses" | "journal" | "general";

type AppRoute = {
  view: AppView;
  courseId?: string;
  isLogin?: boolean;
};

const STORAGE_KEY = "lms-buddy-credentials";
const JOURNAL_PROFILE_KEY = "lms-buddy-journal-profile";
const CACHE_VERSION = "v1";
const DASHBOARD_CACHE_PREFIX = `lms-buddy-cache-${CACHE_VERSION}-dashboard`;
const COURSE_CACHE_PREFIX = `lms-buddy-cache-${CACHE_VERSION}-course`;
const DOWNLOAD_CACHE_PREFIX = `lms-buddy-cache-${CACHE_VERSION}-download`;
const DOWNLOAD_INDEX_PREFIX = `lms-buddy-cache-${CACHE_VERSION}-download-index`;
const HITRATE_CACHE_PREFIX = `lms-buddy-cache-${CACHE_VERSION}-hitrate`;
const MAX_CACHEABLE_DOWNLOAD_SIZE = 2_500_000;

type JournalProfile = {
  name: string;
  usn: string;
  roll: string;
  batch: string;
};

type CachedValue<T> = {
  updatedAt: number;
  data: T;
};

type CachedDownload = {
  filename: string;
  mimeType: string;
  dataUrl: string;
  size: number;
  savedAt: number;
};

type DownloadIndexEntry = {
  key: string;
  size: number;
  updatedAt: number;
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

function cacheScope(username: string): string {
  return encodeURIComponent(username.trim().toLowerCase() || "guest");
}

function dashboardCacheKey(username: string): string {
  return `${DASHBOARD_CACHE_PREFIX}:${cacheScope(username)}`;
}

function courseCacheKey(username: string, courseId: string): string {
  return `${COURSE_CACHE_PREFIX}:${cacheScope(username)}:${courseId}`;
}

function downloadCacheKey(username: string, activityUrl: string): string {
  return `${DOWNLOAD_CACHE_PREFIX}:${cacheScope(username)}:${encodeURIComponent(activityUrl)}`;
}

function downloadIndexKey(username: string): string {
  return `${DOWNLOAD_INDEX_PREFIX}:${cacheScope(username)}`;
}

function readCachedValue<T>(key: string): CachedValue<T> | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedValue<T>;
    if (!parsed || typeof parsed !== "object" || !("data" in parsed)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeCachedValue<T>(key: string, data: T): void {
  try {
    localStorage.setItem(key, JSON.stringify({ updatedAt: Date.now(), data } satisfies CachedValue<T>));
  } catch {
    // Ignore cache write failures.
  }
}

function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return blob.arrayBuffer().then((buffer) => {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunkSize = 0x8000;
    for (let index = 0; index < bytes.length; index += chunkSize) {
      const chunk = bytes.subarray(index, index + chunkSize);
      binary += String.fromCharCode(...chunk);
    }
    return `data:${blob.type || "application/octet-stream"};base64,${btoa(binary)}`;
  });
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [header, base64Data] = dataUrl.split(",", 2);
  if (!header || !base64Data) {
    throw new Error("Invalid cached file data.");
  }
  const mimeMatch = header.match(/^data:([^;]+);base64$/);
  const mimeType = mimeMatch ? mimeMatch[1] : "application/octet-stream";
  const binary = atob(base64Data);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Blob([bytes], { type: mimeType });
}

function loadDownloadIndex(username: string): DownloadIndexEntry[] {
  try {
    const raw = localStorage.getItem(downloadIndexKey(username));
    return raw ? (JSON.parse(raw) as DownloadIndexEntry[]) : [];
  } catch {
    return [];
  }
}

function saveDownloadIndex(username: string, entries: DownloadIndexEntry[]): void {
  try {
    localStorage.setItem(downloadIndexKey(username), JSON.stringify(entries));
  } catch {
    // Ignore cache index write failures.
  }
}

function persistDownloadCache(username: string, key: string, payload: CachedDownload): void {
  if (payload.size > MAX_CACHEABLE_DOWNLOAD_SIZE) return;

  const serialized = JSON.stringify(payload);
  let index = loadDownloadIndex(username).filter((entry) => entry.key !== key);
  const nextEntry = { key, size: payload.size, updatedAt: Date.now() } satisfies DownloadIndexEntry;

  try {
    localStorage.setItem(key, serialized);
    index.unshift(nextEntry);
    saveDownloadIndex(username, index);
    return;
  } catch {
    // Best-effort eviction below.
  }

  while (index.length) {
    const oldest = index.pop();
    if (!oldest) break;
    localStorage.removeItem(oldest.key);
    try {
      localStorage.setItem(key, serialized);
      index.unshift(nextEntry);
      saveDownloadIndex(username, index);
      return;
    } catch {
      // keep evicting until we can write or index is exhausted.
    }
  }
}

function hitrateCacheKey(username: string, courseId: string) {
  return `${HITRATE_CACHE_PREFIX}:${cacheScope(username)}:${courseId}`;
}

function readHitrateCachePct(username: string, courseId: string): number {
  try {
    const raw = localStorage.getItem(hitrateCacheKey(username, courseId));
    if (!raw) return 0;
    const p = JSON.parse(raw) as { pct?: number };
    return typeof p.pct === "number" && !Number.isNaN(p.pct) ? Math.min(100, Math.max(0, Math.round(p.pct))) : 0;
  } catch {
    return 0;
  }
}

function writeHitrateCachePct(username: string, courseId: string, pct: number) {
  try {
    localStorage.setItem(
      hitrateCacheKey(username, courseId),
      JSON.stringify({ pct: Math.min(100, Math.max(0, Math.round(pct))), updatedAt: Date.now() }),
    );
  } catch {
    // ignore
  }
}

function hasDownloadCache(username: string, activityUrl: string): boolean {
  try {
    const key = downloadCacheKey(username, activityUrl);
    const raw = localStorage.getItem(key);
    if (!raw) return false;
    const parsed = JSON.parse(raw) as CachedDownload;
    return Boolean(parsed?.dataUrl);
  } catch {
    return false;
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

function parseRoute(pathname = window.location.pathname): AppRoute {
  if (pathname === "/login") return { view: "courses", isLogin: true };
  if (pathname === "/lab-journal") return { view: "journal" };
  if (pathname === "/tools") return { view: "general" };
  const courseMatch = pathname.match(/^\/courses\/([^/]+)$/);
  if (courseMatch) return { view: "courses", courseId: decodeURIComponent(courseMatch[1]) };
  return { view: "courses" };
}

function viewPath(view: AppView): string {
  if (view === "journal") return "/lab-journal";
  if (view === "general") return "/tools";
  return "/courses";
}

export function App() {
  const [credentials, setCredentials] = useState<Credentials>(() => loadSavedCredentials());
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [selectedCourse, setSelectedCourse] = useState<Course | null>(null);
  const [courseData, setCourseData] = useState<CourseData | null>(null);
  const [route, setRoute] = useState<AppRoute>(() => parseRoute());
  const [journalProfile, setJournalProfile] = useState<JournalProfile>(() => loadJournalProfile());
  const [journalSubject, setJournalSubject] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);
  const [bulkDownloading, setBulkDownloading] = useState(false);
  const [revalidatingDashboard, setRevalidatingDashboard] = useState(false);
  const [dashboardStaleOnly, setDashboardStaleOnly] = useState(false);
  const [revalidatingCourse, setRevalidatingCourse] = useState(false);
  const [courseStaleOnly, setCourseStaleOnly] = useState(false);
  const [downloadListVersion, setDownloadListVersion] = useState(0);
  const bulkCancelRef = useRef(false);
  const activeDownloadControllerRef = useRef<AbortController | null>(null);
  const prefetchedCoursesRef = useRef(new Set<string>());

  const hasSavedCredentials = credentials.username && credentials.password;
  const view = route.view;

  function navigate(path: string, replace = false) {
    if (window.location.pathname !== path) {
      const action = replace ? "replaceState" : "pushState";
      window.history[action](null, "", path);
    }
    setRoute(parseRoute(path));
  }

  useEffect(() => {
    if (hasSavedCredentials) {
      void loadDashboard(credentials);
    } else if (!route.isLogin) {
      navigate("/login", true);
    }
  }, []);

  useEffect(() => {
    const onPopState = () => setRoute(parseRoute());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    prefetchedCoursesRef.current.clear();
  }, [credentials.username]);

  useEffect(() => {
    localStorage.setItem(JOURNAL_PROFILE_KEY, JSON.stringify(journalProfile));
  }, [journalProfile]);

  async function fetchDashboard(nextCredentials = credentials): Promise<DashboardData> {
    return postJson<DashboardData>("/api/dashboard", nextCredentials);
  }

  async function loadDashboard(nextCredentials = credentials, options?: { useCache?: boolean }) {
    const useCache = options?.useCache ?? true;
    const cacheKey = dashboardCacheKey(nextCredentials.username);
    const cached = useCache ? readCachedValue<DashboardData>(cacheKey)?.data : null;
    if (cached) {
      setDashboard(cached);
      setLoading(false);
      setRevalidatingDashboard(true);
      setDashboardStaleOnly(false);
    } else {
      setRevalidatingDashboard(false);
      setDashboardStaleOnly(false);
      setLoading(true);
    }
    setError("");
    try {
      const data = await fetchDashboard(nextCredentials);
      setDashboard(data);
      writeCachedValue(cacheKey, data);
      setDashboardStaleOnly(false);
    } catch (err) {
      if (!cached) {
        setError(err instanceof Error ? err.message : "Unable to load dashboard.");
      } else {
        setDashboardStaleOnly(true);
      }
    } finally {
      setLoading(false);
      setRevalidatingDashboard(false);
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await postJson("/api/login", credentials);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(credentials));
      await loadDashboard(credentials, { useCache: false });
      navigate("/courses", true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  }

  async function loadCourse(course: Course) {
    setSelectedCourse(course);
    const cacheKey = courseCacheKey(credentials.username, course.id);
    const cached = readCachedValue<CourseData>(cacheKey)?.data;
    setCourseData(cached || null);
    if (cached) {
      setLoading(false);
      setRevalidatingCourse(true);
      setCourseStaleOnly(false);
    } else {
      setRevalidatingCourse(false);
      setCourseStaleOnly(false);
      setLoading(true);
    }
    setError("");
    try {
      const data = await postJson<CourseData>("/api/course", {
        ...credentials,
        course_id: course.id,
      });
      setCourseData(data);
      writeCachedValue(cacheKey, data);
      setCourseStaleOnly(false);
    } catch (err) {
      if (!cached) {
        setError(err instanceof Error ? err.message : "Unable to load course.");
      } else {
        setCourseStaleOnly(true);
      }
    } finally {
      setLoading(false);
      setRevalidatingCourse(false);
    }
  }

  function openCourse(course: Course) {
    navigate(`/courses/${encodeURIComponent(course.id)}`);
    void loadCourse(course);
  }

  function closeCourse() {
    setSelectedCourse(null);
    setCourseData(null);
    setRevalidatingCourse(false);
    setCourseStaleOnly(false);
    navigate("/courses");
  }

  async function downloadMaterial(material: Material, signal?: AbortSignal): Promise<"completed" | "cancelled" | "failed"> {
    setDownloading(material.activity_url);
    setError("");
    try {
      const cacheKey = downloadCacheKey(credentials.username, material.activity_url);
      const cached = (() => {
        try {
          const raw = localStorage.getItem(cacheKey);
          return raw ? (JSON.parse(raw) as CachedDownload) : null;
        } catch {
          return null;
        }
      })();
      if (cached?.dataUrl) {
        const blob = dataUrlToBlob(cached.dataUrl);
        downloadBlob(cached.filename || `${material.name || "material"}.download`, blob);
        return "completed";
      }

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
      downloadBlob(filename, blob);
      const dataUrl = await blobToDataUrl(blob);
      persistDownloadCache(credentials.username, cacheKey, {
        filename,
        mimeType: blob.type || "application/octet-stream",
        dataUrl,
        size: blob.size,
        savedAt: Date.now(),
      });
      setDownloadListVersion((n) => n + 1);
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
    setRevalidatingDashboard(false);
    setDashboardStaleOnly(false);
    setRevalidatingCourse(false);
    setCourseStaleOnly(false);
    setCredentials({ username: "", password: "" });
    navigate("/login", true);
  }

  function switchView(nextView: AppView) {
    setSelectedCourse(null);
    setCourseData(null);
    setRevalidatingCourse(false);
    setCourseStaleOnly(false);
    navigate(viewPath(nextView));
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

  useEffect(() => {
    if (!dashboard) return;

    if (route.isLogin) {
      navigate("/courses", true);
      return;
    }

    if (!route.courseId) {
      if (selectedCourse) {
        setSelectedCourse(null);
        setCourseData(null);
        setRevalidatingCourse(false);
        setCourseStaleOnly(false);
      }
      return;
    }

    if (selectedCourse?.id === route.courseId) return;

    const course = dashboard.courses.find((item) => item.id === route.courseId);
    if (course) {
      void loadCourse(course);
    } else {
      navigate("/courses", true);
    }
  }, [dashboard, route.courseId, route.isLogin, selectedCourse]);

  useEffect(() => {
    if (!dashboard?.courses?.length || selectedCourse) return;
    const candidates = dashboard.courses.filter((course) => !prefetchedCoursesRef.current.has(course.id));
    if (!candidates.length) return;
    const timer = window.setTimeout(() => {
      void (async () => {
        for (const course of candidates) {
          prefetchedCoursesRef.current.add(course.id);
          const cacheKey = courseCacheKey(credentials.username, course.id);
          const existing = readCachedValue<CourseData>(cacheKey);
          if (existing) continue;
          try {
            const data = await postJson<CourseData>("/api/course", {
              ...credentials,
              course_id: course.id,
            });
            writeCachedValue(cacheKey, data);
          } catch {
            // Ignore prefetch errors; explicit opens handle retries.
          }
        }
      })();
    }, 200);
    return () => window.clearTimeout(timer);
  }, [dashboard, selectedCourse, credentials]);

  if (!dashboard) {
    return (
      <main className="login-page">
        <section className="login-card">
          <p className="eyebrow">MyDy helper</p>
          <h1>LMS Buddy</h1>
          <p className="muted">Login with LMS credentials. All data is stored locally in your browser.</p>
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
        <AppFooter />
      </main>
    );
  }

  const average = avgAttendance(dashboard.attendance);
  const showSyncing = loading || revalidatingDashboard || revalidatingCourse;
  const showHeaderCached = selectedCourse
    ? revalidatingCourse || courseStaleOnly
    : revalidatingDashboard || dashboardStaleOnly;

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
          <div className="status-row" role="status" aria-live="polite">
            <span className="status-pill">{showSyncing ? "Syncing" : "Ready"}</span>
            {showHeaderCached && (
              <span className="cache-badge" title="Data from local storage; may refresh in the background.">
                Cached
              </span>
            )}
          </div>
        </header>

        {error && <p className="error banner">{error}</p>}

        {selectedCourse ? (
          <CourseDetail
            course={selectedCourse}
            data={courseData}
            loading={loading}
            cacheUsername={credentials.username}
            fileCacheVersion={downloadListVersion}
            downloading={downloading}
            bulkDownloading={bulkDownloading}
            onBack={closeCourse}
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
          <GeneralUtils currentCourses={currentSubjectCourses} credentials={credentials} />
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

function CircularDial({ value, successTone = false }: { value: number; successTone?: boolean }) {
  const v = Math.min(100, Math.max(0, value));
  return (
    <div
      className={`dial${successTone ? " dial--hitrate-high" : ""}`}
      style={{ "--pct": `${v}%` } as React.CSSProperties}
    >
      <div>
        <strong>{Math.round(v)}%</strong>
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
          <h2>
            Cover page generator <span className="soon-tag">Coming soon</span>
          </h2>
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
          <h2>
            Writeup generator <span className="soon-tag">Coming soon</span>
          </h2>
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

function GeneralUtils({
  currentCourses,
  credentials,
}: {
  currentCourses: CurrentSubjectCourse[];
  credentials: Credentials;
}) {
  const [animatingCourseId, setAnimatingCourseId] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, HitrateCourseResult | { error: string }>>({});

  const hitratePercent = (row: HitrateCourseResult) => {
    const total = row.manual_activities ?? 0;
    if (!total) return 0;
    const done = (row.marked ?? 0) + (row.skipped ?? 0);
    return Math.min(100, Math.round((100 * done) / total));
  };

  const runMaxx = async (item: CurrentSubjectCourse) => {
    if (loadingId) return;
    setAnimatingCourseId(null);
    window.setTimeout(() => setAnimatingCourseId(item.course.id), 0);
    setLoadingId(item.course.id);
    try {
      const data = await postJson<HitrateCourseResult>("/api/hitrate", {
        ...credentials,
        course_id: item.course.id,
        course_name: item.course.name,
      });
      setResults((r) => ({ ...r, [item.course.id]: data }));
      writeHitrateCachePct(credentials.username, item.course.id, hitratePercent(data));
    } catch (err) {
      setResults((r) => ({
        ...r,
        [item.course.id]: { error: err instanceof Error ? err.message : "Request failed." },
      }));
    } finally {
      setLoadingId(null);
      window.setTimeout(() => setAnimatingCourseId(null), 1100);
    }
  };

  const displayHitRatePct = (courseId: string) => {
    const row = results[courseId];
    if (row && "error" in row) {
      return readHitrateCachePct(credentials.username, courseId);
    }
    const data = row && !("error" in row) && row.success ? row : null;
    if (data) return hitratePercent(data);
    return readHitrateCachePct(credentials.username, courseId);
  };

  return (
    <section className={`panel hitrate-panel ${animatingCourseId ? "hitrate-panel--active" : ""}`}>
      <div className="section-title">
        <h2>
          Hitrate Maxxer <span className="soon-tag">Beta</span>
        </h2>
        <span>Current courses only</span>
      </div>
      <p className="muted">
        Marks activities that use manual completion on the course page (Moodle checkboxes) via the LMS completion API. Quizzes, forums, and items without
        manual completion are skipped. It may not reach 100% depending on what faculty enabled.
      </p>
      {currentCourses.length ? (
        <div className="subject-grid">
          {currentCourses.map((item) => {
            const row = results[item.course.id];
            const data = row && "error" in row ? null : row;
            const err = row && "error" in row ? row.error : null;
            const hitRatePct = displayHitRatePct(item.course.id);
            const busy = loadingId === item.course.id;
            const atFullHitRate = hitRatePct >= 100;
            const highHitRate = hitRatePct > 80;
            return (
              <article
                className={`utility-course-card hitrate-card ${
                  animatingCourseId === item.course.id ? "hitrate-card--active" : ""
                }`}
                key={item.course.id}
              >
                <CircularDial value={hitRatePct} successTone={highHitRate} />
                <div>
                  <strong>{item.attendance.subject}</strong>
                  <p className={`hitrate-pct-line${highHitRate ? " hitrate-pct-line--high" : ""}`}>
                    Hit rate <strong>{`${hitRatePct}%`}</strong>
                  </p>
                  {data?.success && (
                    <small>
                      {data.marked ?? 0} marked · {data.skipped ?? 0} already done
                      {!!data.failed && ` · ${data.failed} failed`}
                    </small>
                  )}
                  {err && <small className="hitrate-error">{err}</small>}
                </div>
                <button
                  className={`hitrate-button ${busy ? "hitrate-button--glowing" : ""}`}
                  type="button"
                  disabled={Boolean(loadingId) || atFullHitRate}
                  onClick={() => void runMaxx(item)}
                >
                  {busy ? "Maxxing…" : atFullHitRate ? "100% hit rate" : "Maxxing"}
                </button>
              </article>
            );
          })}
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
  cacheUsername,
  fileCacheVersion,
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
  cacheUsername: string;
  fileCacheVersion: number;
  downloading: string | null;
  bulkDownloading: boolean;
  onBack: () => void;
  onDownload: (material: Material) => void;
  onDownloadAll: (materials: Material[]) => void;
  onCancelDownloadAll: () => void;
}) {
  const materials = data && typeof data.materials !== "string" ? data.materials.materials : [];
  const materialRows = useMemo(
    () =>
      materials.map((material) => ({
        material,
        fileCached: hasDownloadCache(cacheUsername, material.activity_url),
      })),
    [materials, cacheUsername, fileCacheVersion],
  );
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
            materialRows.map(({ material, fileCached }) => (
                <div className="document-row" key={material.activity_url}>
                  <div>
                    <strong>{material.name}</strong>
                    <span className="document-type-row">
                      {material.type}
                      {fileCached && (
                        <span className="cache-badge cache-badge--file" title="This file is stored locally; repeat downloads are instant.">
                          File cached
                        </span>
                      )}
                    </span>
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
