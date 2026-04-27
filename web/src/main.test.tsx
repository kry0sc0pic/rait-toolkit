import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./main";

const credentials = {
  username: "student@example.edu",
  password: "password123",
};

const dashboardPayload = {
  success: true,
  courses: [
    { id: "101", name: "Machine Learning", url: "https://mydy.dypatil.edu/rait/course/view.php?id=101" },
    { id: "102", name: "Computer Vision", url: "https://mydy.dypatil.edu/rait/course/view.php?id=102" },
  ],
  current_courses: [
    { id: "101", name: "Machine Learning", url: "https://mydy.dypatil.edu/rait/course/view.php?id=101" },
  ],
  attendance: {
    batch: "RT-23",
    semester: "Semester 6",
    subjects: [
      {
        subject: "Machine Learning",
        total_classes: 20,
        present: 18,
        absent: 2,
        percentage: 90,
      },
    ],
  },
};

const coursePayload = {
  success: true,
  content: [
    {
      section_name: "Unit 1",
      activities: [{ name: "Intro Notes", type: "resource", url: "https://example.test/notes" }],
    },
  ],
  assignments: [
    {
      name: "Assignment 1",
      due_date: "Tomorrow",
      submission_status: "Submitted",
      grading_status: "Graded",
      grade: "9/10",
    },
  ],
  grades: {
    grade_items: [{ name: "Quiz 1", grade: "8", range: "0-10", percentage: "80%" }],
    course_total: { grade: "A", percentage: "90%" },
  },
  announcements: [{ title: "Class update", author: "Faculty", date: "Today", content: "Bring your laptop." }],
  materials: {
    course_name: "Machine Learning",
    materials: [{ name: "Intro Notes", type: "resource", activity_url: "https://mydy.dypatil.edu/rait/mod/resource/view.php?id=1" }],
  },
};

function jsonResponse(payload: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/login");
  vi.restoreAllMocks();
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:lms-buddy");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LMS Buddy", () => {
  it("logs in with website-entered credentials, stores them by default, and shows current courses", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = input.toString();
      if (url === "/api/login") return jsonResponse({ success: true });
      if (url === "/api/dashboard") return jsonResponse(dashboardPayload);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await userEvent.type(screen.getByPlaceholderText("Username / Email"), credentials.username);
    await userEvent.type(screen.getByPlaceholderText("Password"), credentials.password);
    expect(screen.queryByLabelText("Store credentials in localStorage")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Courses" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/courses");
    expect(screen.getByRole("heading", { name: "Courses and attendance" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Current Courses" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Machine Learning/ })).toBeInTheDocument();
    expect(screen.getAllByText("90%").length).toBeGreaterThan(0);
    expect(screen.getByText("Older subjects")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Deeptanshu" })).toHaveAttribute("href", "https://github.com/Deeptanshuu");
    expect(screen.getByRole("link", { name: "Krishaay" })).toHaveAttribute("href", "https://github.com/kry0sc0pic");
    expect(screen.getByRole("link", { name: "Claude Code" })).toHaveAttribute("href", "https://claude.ai");
    expect(screen.getByRole("link", { name: "Cursor" })).toHaveAttribute("href", "https://cursor.com/agents");
    expect(screen.getByRole("link", { name: "GitHub" })).toHaveAttribute("href", "https://github.com/kry0sc0pic/mydy-lms-scraper");
    expect(JSON.parse(localStorage.getItem("lms-buddy-credentials") || "{}")).toEqual(credentials);
  });

  it("loads saved localStorage credentials on startup and clears them on logout", async () => {
    localStorage.setItem("lms-buddy-credentials", JSON.stringify(credentials));
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(dashboardPayload)));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Courses" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /logout/i }));

    expect(localStorage.getItem("lms-buddy-credentials")).toBeNull();
    expect(window.location.pathname).toBe("/login");
    expect(screen.getByRole("heading", { name: "LMS Buddy" })).toBeInTheDocument();
  });

  it("restores a direct course URL after saved credentials load", async () => {
    localStorage.setItem("lms-buddy-credentials", JSON.stringify(credentials));
    window.history.replaceState(null, "", "/courses/101");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = input.toString();
        if (url === "/api/dashboard") return jsonResponse(dashboardPayload);
        if (url === "/api/course") return jsonResponse(coursePayload);
        throw new Error(`Unexpected request: ${url}`);
      }),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Machine Learning", level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/courses/101");
  });

  it("opens course details and downloads a material through the API", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = input.toString();
      if (url === "/api/login") return jsonResponse({ success: true });
      if (url === "/api/dashboard") return jsonResponse(dashboardPayload);
      if (url === "/api/course") return jsonResponse(coursePayload);
      if (url === "/api/download") {
        return new Response("file-content", {
          status: 200,
          headers: {
            "content-disposition": "attachment; filename*=UTF-8''intro.pdf",
            "content-type": "application/pdf",
          },
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    await userEvent.type(screen.getByPlaceholderText("Username / Email"), credentials.username);
    await userEvent.type(screen.getByPlaceholderText("Password"), credentials.password);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await userEvent.click(await screen.findByRole("button", { name: /Machine Learning/ }));

    expect(await screen.findByRole("heading", { name: "Machine Learning", level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/courses/101");
    expect(screen.getByText("Downloads are proxied through LMS Buddy. Large files may take time or hit Vercel limits.")).toBeInTheDocument();
    expect(screen.getAllByText("resource").length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "Download" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/download", expect.any(Object)));
    const downloadCall = fetchMock.mock.calls.find(([url]) => url === "/api/download") as
      | [RequestInfo | URL, RequestInit]
      | undefined;
    expect(JSON.parse(String(downloadCall?.[1].body))).toMatchObject({
      username: credentials.username,
      activity_url: "https://mydy.dypatil.edu/rait/mod/resource/view.php?id=1",
    });
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Assignments" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(screen.getByRole("heading", { name: "Tools", level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/tools");
    expect(screen.queryByRole("heading", { name: "Machine Learning", level: 1 })).not.toBeInTheDocument();
  });

  it("shows lab journal and tools tabs, and persists journal profile details", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(dashboardPayload)));

    render(<App />);

    await userEvent.type(screen.getByPlaceholderText("Username / Email"), credentials.username);
    await userEvent.type(screen.getByPlaceholderText("Password"), credentials.password);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await userEvent.click(await screen.findByRole("button", { name: "Lab / Journal" }));
    expect(window.location.pathname).toBe("/lab-journal");
    expect(screen.getByPlaceholderText("Name")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("USN number")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Batch / Course")).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("Name"), "Test Student");
    await userEvent.type(screen.getByPlaceholderText("USN number"), "USN001");
    await userEvent.type(screen.getByPlaceholderText("Roll number"), "42");
    await userEvent.type(screen.getByPlaceholderText("Batch / Course"), "AIML B");
    expect(JSON.parse(localStorage.getItem("lms-buddy-journal-profile") || "{}")).toMatchObject({
      name: "Test Student",
      usn: "USN001",
      roll: "42",
      batch: "AIML B",
    });
    expect(screen.getByRole("button", { name: /Generate CO\/PO cover sheet/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Cover page generator Coming soon" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Writeup generator Coming soon" })).toBeInTheDocument();
    expect(screen.getByText("BETA Feature")).toBeInTheDocument();
    expect(screen.getByText("Use AI to generate journal-ready writeups and code from experiment aims.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create journal writeups/ })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Tools" }));
    expect(screen.getByRole("heading", { name: "Tools", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Hitrate Maxxer Coming soon", level: 2 })).toBeInTheDocument();
    expect(screen.getByText(/Attempts to open all LMS resources/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Select subject")).not.toBeInTheDocument();
    expect(screen.getByText("Hitrate percentage will be populated later.")).toBeInTheDocument();
    const hitrateButton = screen.getByRole("button", { name: "Execute maxxing" });
    expect(hitrateButton).toBeEnabled();
    await userEvent.click(hitrateButton);
    expect(hitrateButton.closest(".hitrate-card")).toHaveClass("hitrate-card--active");
  });
});
