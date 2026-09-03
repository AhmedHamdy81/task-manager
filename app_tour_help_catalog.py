"""Illustrated Take a Tour help pages for each major app area."""

from __future__ import annotations

from typing import Any, Callable


def build_tour_help_catalog(_: Callable[..., str]) -> dict[str, dict[str, Any]]:
    """Return help page definitions keyed by slug. Call at request time for i18n."""

    def page(
        title: str,
        summary: str,
        *,
        open_endpoint: str | None = None,
        open_kwargs: dict[str, Any] | None = None,
        open_label: str | None = None,
        redirect_to: str | None = None,
        sections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "title": title,
            "summary": summary,
            "open_endpoint": open_endpoint,
            "open_kwargs": open_kwargs or {},
            "open_label": open_label or _("Open this area"),
            "redirect_to": redirect_to,
            "sections": sections or [],
        }

    def section(
        sid: str,
        title: str,
        *,
        paragraphs: list[str] | None = None,
        bullets: list[str] | None = None,
        dl: list[tuple[str, str]] | None = None,
        shots: list[dict[str, str]] | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": sid,
            "title": title,
            "paragraphs": paragraphs or [],
            "bullets": bullets or [],
            "dl": [{"term": t, "definition": d} for t, d in (dl or [])],
            "shots": shots or [],
            "note": note,
        }

    def shot(filename: str, alt: str, caption: str, *, folder: str = "img/tour-help") -> dict[str, str]:
        return {
            "src": f"{folder}/{filename}",
            "alt": alt,
            "caption": caption,
        }

    return {
        "dashboard": page(
            _("Dashboard"),
            _("Your home screen after sign-in — counts, today’s bookings, and shortcuts into the work that needs attention."),
            open_endpoint="index",
            open_label=_("Open Dashboard"),
            sections=[
                section(
                    "overview",
                    _("What you see"),
                    paragraphs=[
                        _("The Dashboard is the daily launch pad. It surfaces project and task counts, critical items, Machine Room work (for storage roles), booking for today, and optional Industry Radar / What’s New cards."),
                        _("What appears depends on your role: VFX artists see shot counts, Machine Room accounts see storage-oriented widgets, guests see a reduced set."),
                    ],
                    shots=[
                        shot(
                            "dashboard.png",
                            _("Dashboard overview"),
                            _("Dashboard: welcome header, stat widgets, My booking, and Session."),
                        )
                    ],
                ),
                section(
                    "welcome",
                    _("Welcome header"),
                    paragraphs=[
                        _("At the top of the page you see a personal greeting (your display name) and a short tagline. This is not a button — it only confirms you are signed in."),
                    ],
                ),
                section(
                    "stat-widgets",
                    _("Stat widgets"),
                    paragraphs=[
                        _("The left grid of cards is the fastest way into each area. Click a card to open that list or hub. Counts refresh when you reload the Dashboard."),
                    ],
                    dl=[
                        (
                            _("Projects"),
                            _("How many productions you can access. Opens the Projects list (or Machine Room / VFX hub for those roles)."),
                        ),
                        (
                            _("Users"),
                            _("Admin-only. Total people in the directory. Opens Users."),
                        ),
                        (
                            _("My open / Open tasks"),
                            _("Open work assigned to you (or all open tasks for admins). VFX job titles see open VFX shots instead. Opens the filtered Tasks list or VFX Department."),
                        ),
                        (
                            _("Requests"),
                            _("Shows requested · to-complete counts. Opens Requests: work you asked for, and work assigned to you to complete."),
                        ),
                        (
                            _("Notes"),
                            _("Count of pinned notes on your board. Opens Notes (Actions)."),
                        ),
                        (
                            _("Criticals / Overdue"),
                            _("Open critical production notes, or overdue VFX shots for VFX artists. Opens Criticals or VFX Department."),
                        ),
                        (
                            _("Missing info"),
                            _("Incomplete project or media metadata that still needs attention. Opens Missing information."),
                        ),
                        (
                            _("my BigClock"),
                            _("Machine Room roles only. Live device clock on the dashboard; not a link."),
                        ),
                    ],
                ),
                section(
                    "my-booking",
                    _("My booking"),
                    paragraphs=[
                        _("The right column is your personal booking glance for today. It is hidden for Machine Room–only accounts."),
                    ],
                    dl=[
                        (
                            _("Clock and date"),
                            _("Live device time so you can compare against suite start/end times."),
                        ),
                        (
                            _("Mini calendar"),
                            _("Month view for context. Clicking the card opens Manage booking / schedule."),
                        ),
                        (
                            _("Today’s slot"),
                            _("Shows suite name, time range, project, and who the booking is for. If nothing is booked, you see “No booking today”."),
                        ),
                        (
                            _("Remind me"),
                            _("Creates a Notes reminder tied to a date (when you can create notes). Use it to remember call times or handoffs."),
                        ),
                    ],
                ),
                section(
                    "session",
                    _("Session (Working Hours)"),
                    paragraphs=[
                        _("The wide Session card tracks live work in a suite. It only appears when your role may start work sessions."),
                    ],
                    dl=[
                        (
                            _("Start session"),
                            _("Opens a dialog: pick Project, a free Room, Job type, and Duration. Starting books the room for that window."),
                        ),
                        (
                            _("Elapsed timer"),
                            _("While a session runs, the green timer shows how long you have been working, plus project / room / job meta."),
                        ),
                        (
                            _("End session"),
                            _("Stops the timer and frees the room early if you finish before the booked window."),
                        ),
                        (
                            _("Today / Billable"),
                            _("Quick totals from today’s Working Hours ledger."),
                        ),
                        (
                            _("Add Manual Hours / View My Hours"),
                            _("Jump to the project Working Hours page to log time without a live session, or review your entries."),
                        ),
                    ],
                    note=_("If every room is busy, Start session will show that no free suites are available until someone ends a booking."),
                ),
                section(
                    "insights",
                    _("What’s New and Industry Radar"),
                    paragraphs=[
                        _("Below the widgets, the Dashboard can show What’s New (product updates) and Industry Radar headlines when those features are enabled for your account."),
                    ],
                    bullets=[
                        _("What’s New may be disabled in some deployments — the section can appear greyed out."),
                        _("Industry Radar cards open the full Radar page for search and filters."),
                    ],
                ),
            ],
        ),
        "industry-radar": page(
            _("Industry Radar"),
            _("Curated film and TV industry news for the studio — not a project tool, but shared context for producers and leads."),
            open_endpoint="industry_radar_page",
            open_label=_("Open Industry Radar"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Industry Radar lists news items pulled from configured sources and curated in Admin. Use it to stay aware of festivals, market moves, and production news without leaving the app."),
                    ],
                    bullets=[
                        _("Browse by category and region when filters are available."),
                        _("Admins manage sources and items under News sources / Industry news."),
                    ],
                    shots=[
                        shot(
                            "industry-radar.png",
                            _("Industry Radar page"),
                            _("Industry Radar: curated headlines for the team."),
                        )
                    ],
                ),
            ],
        ),
        "chat": page(
            _("Chat"),
            _("Team messaging and conference rooms for day-to-day coordination."),
            open_endpoint="chat_page",
            open_label=_("Open Chat"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Chat is the in-app conversation hub. Open direct or group threads, and use conference rooms when a longer discussion needs its own space."),
                    ],
                    bullets=[
                        _("Notifications badge in the top bar alerts you to unread activity."),
                        _("Guests typically do not get Chat — it is for approved studio accounts."),
                    ],
                    shots=[
                        shot(
                            "chat.png",
                            _("Chat page"),
                            _("Chat: threads and conference rooms for the team."),
                        )
                    ],
                ),
            ],
        ),
        "audio-library": page(
            _("Audio Library"),
            _("Shared music and sound mounts used across post — browse, play, and scan cataloged audio."),
            open_endpoint="music_library",
            open_label=_("Open Audio Library"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("The global Audio Library connects to configured mounts (network shares or folders). Editors and sound can preview tracks without leaving the browser."),
                        _("Projects also have a project-scoped Audio Library in the workflow bar for show-specific material."),
                    ],
                    shots=[
                        shot(
                            "audio-library.png",
                            _("Audio Library"),
                            _("Audio Library: sources above, then Folders · Files · Inspector."),
                        )
                    ],
                ),
                section(
                    "sources",
                    _("Audio Sources"),
                    paragraphs=[
                        _("Managers who can manage mounts see the Audio Sources panel at the top. Everyone else starts at the browse workspace."),
                    ],
                    dl=[
                        (
                            _("Drop folder here"),
                            _("Drag a folder (desktop app) to suggest a path. In the browser you usually type the path after /Volumes/ instead."),
                        ),
                        (
                            _("Path field"),
                            _("Enter the folder under /Volumes/ (for example DriveName/Media/Music). Validate checks the path before you add it."),
                        ),
                        (
                            _("Library type"),
                            _("Choose Music or SFX so sources can be filtered later."),
                        ),
                        (
                            _("Validate"),
                            _("Confirms the path is reachable before Add Source. Status text appears under the form."),
                        ),
                        (
                            _("Add Source"),
                            _("Registers the mount in the catalog. Files on disk are not moved or copied — only indexed."),
                        ),
                        (
                            _("All / Music / SFX filters"),
                            _("Show only sources of that library type in the source card list."),
                        ),
                    ],
                ),
                section(
                    "source-cards",
                    _("Source cards"),
                    paragraphs=[
                        _("Each registered mount is a card with path, index stats, and actions."),
                    ],
                    dl=[
                        (
                            _("Browse"),
                            _("Opens that mount in the folder/file panels below."),
                        ),
                        (
                            _("Scan / ReScan"),
                            _("Walks the folder tree and indexes files into the library. ReScan refreshes after files change on disk."),
                        ),
                        (
                            _("Remove Source"),
                            _("Deletes the catalog entry only. Original audio stays on the drive."),
                        ),
                        (
                            _("Category select"),
                            _("Switch the source between Music and SFX without re-adding it."),
                        ),
                        (
                            _("Indexed stats"),
                            _("Shows how many files and folders were last indexed (or “Not scanned” if never scanned)."),
                        ),
                    ],
                ),
                section(
                    "workspace",
                    _("Folders, Files, and Inspector"),
                    paragraphs=[
                        _("The main workspace is three columns. Search sits above them when you are browsing."),
                    ],
                    dl=[
                        (
                            _("Search"),
                            _("Find tracks across indexed sources. Leaving search returns you to Browse library."),
                        ),
                        (
                            _("Breadcrumb"),
                            _("Shows where you are in the folder tree; click segments to jump up."),
                        ),
                        (
                            _("Folders"),
                            _("Directory tree for the selected source. Click a folder to list its files."),
                        ),
                        (
                            _("Files"),
                            _("Audio files in the selected folder. Select a file to load the Inspector and preview."),
                        ),
                        (
                            _("Inspector"),
                            _("Details for the selected folder or file (name, type, usage). Empty until you select something."),
                        ),
                    ],
                ),
                section(
                    "playback",
                    _("Playback and the global dock"),
                    paragraphs=[
                        _("Previewing a track can keep playing in the global audio dock at the bottom of the app while you navigate elsewhere."),
                    ],
                    bullets=[
                        _("Use play/pause and volume on the dock."),
                        _("The waveform supports scrubbing; keyboard shortcuts follow the dock hints (Space, arrows, wheel zoom)."),
                        _("Stopping or clearing the dock ends playback for the session."),
                    ],
                ),
            ],
        ),
        "notes": page(
            _("Notes"),
            _("Personal and shared action boards — todos, sticky notes, and follow-ups that are not full project tasks."),
            open_endpoint="actions_page",
            open_label=_("Open Notes"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Notes (Actions) is a lightweight board for todos and sticky notes. Use it for personal reminders or small team actions that do not belong on a project task list."),
                    ],
                    shots=[
                        shot(
                            "notes.png",
                            _("Notes / Actions page"),
                            _("Notes: filters on top, then tabs and sticky cards."),
                        )
                    ],
                ),
                section(
                    "filters",
                    _("Search and filters"),
                    paragraphs=[
                        _("The filter bar narrows which notes appear. Combine search, project, color, sort, and quick toggles, then Reset to clear."),
                    ],
                    dl=[
                        (
                            _("Search"),
                            _("Matches title, body, or project name."),
                        ),
                        (
                            _("All projects"),
                            _("Limit notes to one production, or keep All projects."),
                        ),
                        (
                            _("All colors"),
                            _("Filter by sticky color (yellow, blue, green, and others)."),
                        ),
                        (
                            _("Sort"),
                            _("Order by Updated, Due date, Priority, Created, or Project."),
                        ),
                        (
                            _("Pinned / Due today / Overdue / Archived"),
                            _("Quick toggles. Archived shows notes you hid from the active board."),
                        ),
                        (
                            _("Reset"),
                            _("Clears every filter and returns to the default board view."),
                        ),
                    ],
                ),
                section(
                    "board",
                    _("Board header and tabs"),
                    paragraphs=[
                        _("Under the filters, the Notes panel shows counts and the sticky grid."),
                    ],
                    dl=[
                        (
                            _("Add note"),
                            _("Opens the quick-add dialog: optional title, rich body, project, assignee, color, due date, and pin."),
                        ),
                        (
                            _("My Notes"),
                            _("Notes assigned to you or created as personal."),
                        ),
                        (
                            _("Pinned"),
                            _("Notes marked pinned — they stay visible on the sticky board."),
                        ),
                        (
                            _("All"),
                            _("Every note you are allowed to see (subject to filters)."),
                        ),
                        (
                            _("? help"),
                            _("Short tip about formatting, ⌘/Ctrl+Enter to save, and card footer icons."),
                        ),
                    ],
                ),
                section(
                    "cards",
                    _("Note cards"),
                    paragraphs=[
                        _("Each sticky is a card. The dashed “New note” tile is another way to open quick-add."),
                    ],
                    dl=[
                        (
                            _("PINNED badge"),
                            _("Shows when the note is pinned to the board."),
                        ),
                        (
                            _("Body and @mentions"),
                            _("Rich text can include checklists, links, and @people from the mention list."),
                        ),
                        (
                            _("Footer icons"),
                            _("Edit, pin/unpin, recolor, archive, share, or delete (delete may require Safe Delete)."),
                        ),
                        (
                            _("Edit dialog"),
                            _("Full editor for title and body. Drag the resize handle if you need more space."),
                        ),
                    ],
                    note=_("Dashboard “Remind me” on My booking creates Notes reminders — they show up here with a due date."),
                ),
            ],
        ),
        "storage": page(
            _("Storage"),
            _("The Machine Room volumes dashboard — capacity, free space, and linked storage across projects."),
            open_endpoint="machine_room_dashboard_index",
            open_label=_("Open Storage"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Storage opens the Machine Room dashboard on the Volumes view. Watch free space, mount status, critical volumes, and jump into ingest, backup, and transcode tabs."),
                        _("For a full illustrated walkthrough of every control, open Machine Room Help from the tour or the dashboard Help button."),
                    ],
                    bullets=[
                        _("Volumes tab: browse and manage disks / NAS / shares."),
                        _("Section cards jump to Projects, Ingest, Backups, Transcode, Health, Missing, and more."),
                    ],
                    shots=[
                        shot(
                            "storage.png",
                            _("Storage / Volumes dashboard"),
                            _("Storage dashboard: volume cards and capacity summary."),
                        )
                    ],
                    note=_("Deep dive: Machine Room Help covers every button and tab with live screenshots."),
                ),
            ],
        ),
        "machine-room": page(
            _("Machine room"),
            _("Classic project-oriented Machine Room list and storage entry points — ingest, backup, and transcode live here and on the Storage dashboard."),
            open_endpoint="machine_room",
            open_label=_("Open Machine room"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Machine room is the project-oriented entry to storage operations. From here you open per-project Machine Room views and jump into the volumes dashboard."),
                        _("For every button and tab with live screenshots, use Machine Room Help."),
                    ],
                    bullets=[
                        _("Storage dashboard: global volumes, capacity, and media workflows."),
                        _("Project Machine Room: storage focused on one show."),
                    ],
                    shots=[
                        shot(
                            "storage.png",
                            _("Machine Room / Storage"),
                            _("Machine Room storage dashboard used alongside the classic Machine room list."),
                        )
                    ],
                    note=_("Deep dive: Machine Room Help covers every button and tab with live screenshots."),
                ),
            ],
        ),
        "machine-room-help": page(
            _("Machine Room Help"),
            _("Illustrated guide to Storage and Machine Room workflows."),
            redirect_to="machine_room_help",
            sections=[],
        ),
        "tasks": page(
            _("Tasks"),
            _("Open and assigned work — either the studio task list or the Machine Room progress board, depending on your role."),
            open_endpoint="tasks_list",
            open_label=_("Open Tasks"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Tasks tracks work items across projects: assignments, status, and filters such as My open."),
                        _("Machine Room role accounts use a dedicated Tasks progress board under Machine Room instead of the general list."),
                    ],
                    bullets=[
                        _("Open a task to update status, notes, and attachments when you have permission."),
                        _("Dashboard widgets deep-link into the filtered list that matches your role."),
                    ],
                    shots=[
                        shot(
                            "tasks.png",
                            _("Tasks list"),
                            _("Tasks: open and assigned work across projects."),
                        )
                    ],
                ),
            ],
        ),
        "projects": page(
            _("Projects"),
            _("Every production you can access — open one to use the full workflow bar (Overview, Team, portals, and more)."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Projects is the directory of shows and films. Cards open the project Overview and unlock the horizontal workflow navigation for that production."),
                    ],
                    bullets=[
                        _("Filter and search when many shows are listed."),
                        _("From a project you reach Editing Item, Shooting days, VFX / Color portals, Post Pipeline, Working Hours, and Log Book."),
                    ],
                    shots=[
                        shot(
                            "projects.png",
                            _("Projects list"),
                            _("Projects: productions available to your account."),
                        )
                    ],
                ),
            ],
        ),
        "booking": page(
            _("Booking"),
            _("Edit suite and room schedules — see who is booked where, and manage availability."),
            open_endpoint="booking.booking_home",
            open_label=_("Open Booking"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Booking shows suite calendars so editorial and finishing rooms are not double-booked. Book for yourself or others when your role allows management."),
                    ],
                    shots=[
                        shot(
                            "booking.png",
                            _("Booking calendar"),
                            _("Booking: month picker and form on the left, room timeline on the right."),
                        )
                    ],
                ),
                section(
                    "month",
                    _("Month calendar"),
                    paragraphs=[
                        _("The left calendar picks the day you are scheduling. Prev / Today / Next move the month."),
                    ],
                    dl=[
                        (
                            _("Day selection"),
                            _("Click a date to load that day’s timeline and fill the hidden date field for the form."),
                        ),
                        (
                            _("Today"),
                            _("Jumps back to the current date quickly."),
                        ),
                    ],
                ),
                section(
                    "form",
                    _("Booking details form"),
                    paragraphs=[
                        _("Fill the form, then Book now. You can also click or drag on the timeline to reserve a slot, which pre-fills times."),
                    ],
                    dl=[
                        (
                            _("Room"),
                            _("Edit suite (Bang rooms, etc.). Suites are configured under Admin → Edit suites."),
                        ),
                        (
                            _("Project"),
                            _("Which production this booking is for."),
                        ),
                        (
                            _("Start / End"),
                            _("Time window. Conflicts appear on the timeline if the room is already taken."),
                        ),
                        (
                            _("Booked for"),
                            _("Who the suite is reserved for (yourself or another directory user when permitted)."),
                        ),
                        (
                            _("Job"),
                            _("Work type: Sync, Selection, Assembly, Offline/Online Editing, Color Grading, and similar."),
                        ),
                        (
                            _("Notes"),
                            _("Optional free text for the booking."),
                        ),
                        (
                            _("Repeat"),
                            _("None, Daily, or Weekly with an optional Repeat until date for recurring blocks."),
                        ),
                        (
                            _("Book now"),
                            _("Saves the booking. Errors (conflicts, missing fields) show under the form."),
                        ),
                        (
                            _("Manage"),
                            _("Opens the manage schedule page (also linked from Dashboard My booking)."),
                        ),
                        (
                            _("Delete"),
                            _("Appears when editing an existing booking; uses Safe Delete when required."),
                        ),
                    ],
                ),
                section(
                    "timeline",
                    _("Schedule timeline"),
                    paragraphs=[
                        _("The large center view is the room grid. Rows are suites; columns are hours of the day (or week/month depending on scope)."),
                    ],
                    dl=[
                        (
                            _("Daily / Weekly / Monthly"),
                            _("Calendar scope in the toolbar. Daily is the usual booking view."),
                        ),
                        (
                            _("Date toolbar"),
                            _("Today and arrows move the visible range without leaving the timeline."),
                        ),
                        (
                            _("Booking blocks"),
                            _("Colored bars show existing reservations (project name on the block). Click a block to load it into the form for edit/delete when allowed."),
                        ),
                        (
                            _("Click or drag"),
                            _("Create a new reservation by selecting an empty span on a room row — times fill into Start/End."),
                        ),
                    ],
                    note=_("Dashboard My booking shows only your today’s slot. Use Booking for the full studio timeline."),
                ),
            ],
        ),
        "producer-hunt": page(
            _("Producer Hunt"),
            _("A lightweight entertainment break for the team — not part of production delivery."),
            open_endpoint="producer_hunt_page",
            open_label=_("Open Producer Hunt"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Producer Hunt is a fun mini-game area for downtime. It does not affect projects, tasks, or storage."),
                    ],
                    shots=[
                        shot(
                            "producer-hunt.png",
                            _("Producer Hunt"),
                            _("Producer Hunt: optional entertainment for the team."),
                        )
                    ],
                ),
            ],
        ),
        "profile": page(
            _("Profile"),
            _("Your account details, display name, and preferences."),
            open_endpoint="profile",
            open_label=_("Open Profile"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Profile is where you review your account, avatar, and personal settings. Sign out is available from the sidebar user block as well."),
                    ],
                    shots=[
                        shot(
                            "profile.png",
                            _("Profile page"),
                            _("Profile: account and preference settings."),
                        )
                    ],
                ),
            ],
        ),
        # Inside a project
        "project-overview": page(
            _("Overview"),
            _("Project home — status and entry point for the production workflow bar."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("After you open a project, Overview is the first workflow tab. It summarizes the show and links into the rest of production tools."),
                    ],
                    bullets=[
                        _("Use the top workflow bar to move between Team, Shooting days, portals, and more."),
                        _("TV series may show Editing Item (episodes) in that bar."),
                    ],
                    shots=[
                        shot(
                            "project-overview.png",
                            _("Project Overview"),
                            _("Project Overview with the production workflow navigation."),
                        )
                    ],
                ),
            ],
        ),
        "project-team": page(
            _("Team"),
            _("Crew on this production, grouped by post-production scope — manage who can receive tasks for each department."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What this page is"),
                    paragraphs=[
                        _("Team is the project roster. People must be on the team before you can assign them project tasks."),
                        _("You do not create free-form “teams” by name. Instead, the page shows one card per post-production scope enabled in Project Settings (for example Offline Editing, VFX, Color Grading). Each card is that scope’s crew for this show."),
                    ],
                    shots=[
                        shot(
                            "project-team.png",
                            _("Project Team page"),
                            _("Team page: scope cards for Offline Editing, Color, VFX, and more."),
                        )
                    ],
                ),
                section(
                    "scopes",
                    _("Scope cards (the “teams”)"),
                    paragraphs=[
                        _("Each colored card is one post-production scope. Which cards appear depends on which scopes are turned on for the project in Settings."),
                    ],
                    dl=[
                        (
                            _("Offline Editing"),
                            _("Editors and assistants who work assembly and picture lock."),
                        ),
                        (
                            _("Online Editing"),
                            _("Conform and finishing editors when that scope is enabled."),
                        ),
                        (
                            _("Color Grading / VFX / Sound / Music / …"),
                            _("Department crews for those workflows."),
                        ),
                        (
                            _("Post-production Team"),
                            _("Supervisors and producers. They often appear as Oversight on department cards and may show “Covers: …” for the scopes they coordinate."),
                        ),
                        (
                            _("Client / Guest"),
                            _("External clients and guest reviewers. Non-employees can be added here when policy allows."),
                        ),
                        (
                            _("Team"),
                            _("General project members (for example admins) who are not tied to a specific post scope."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-team-scopes.png",
                            _("Team scope cards"),
                            _("Each card lists members, job titles, employment badges, and oversight."),
                        )
                    ],
                    note=_("Turn scopes on or off in Project Settings. New scopes create empty cards; they are not created from the Team page itself."),
                ),
                section(
                    "card-elements",
                    _("What you see on a card"),
                    dl=[
                        (
                            _("Member count"),
                            _("How many people are linked to this scope on the project."),
                        ),
                        (
                            _("Oversight count"),
                            _("Coordinators (often from Post-production Team) who oversee this scope."),
                        ),
                        (
                            _("Member name + job title"),
                            _("Directory name and lead job title (Senior Editor, Head of VFX, and so on)."),
                        ),
                        (
                            _("Employment badge"),
                            _("In-house, Freelancer, Vendor, Client, etc. — from Employment structure."),
                        ),
                        (
                            _("Covers"),
                            _("On Post-production Team cards: which department scopes that person coordinates."),
                        ),
                        (
                            _("Manage"),
                            _("Opens the manage dialog for that scope (only if you may manage that scope)."),
                        ),
                    ],
                ),
                section(
                    "manage",
                    _("How to manage a team (add / remove)"),
                    paragraphs=[
                        _("Click Manage on a scope card. The dialog title becomes “Manage … Team” for that scope."),
                    ],
                    dl=[
                        (
                            _("Current members"),
                            _("People already on the project for this scope. Remove removes them from the project team (with confirmation)."),
                        ),
                        (
                            _("Search"),
                            _("Find directory users by name or email. The picker is filtered to people eligible for this scope."),
                        ),
                        (
                            _("Add to project"),
                            _("Adds the selected person to the project team for this scope so they can receive related tasks."),
                        ),
                        (
                            _("Employment & scope checks"),
                            _("Expand this help in the dialog for policy details when an add is blocked."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-team-manage.png",
                            _("Manage Offline Editing Team dialog"),
                            _("Manage dialog: current members with Remove, search, and Add to project."),
                        )
                    ],
                ),
                section(
                    "roles-policy",
                    _("Who can be added (roles & policy)"),
                    paragraphs=[
                        _("Adding someone is not only “pick any user.” The app checks employment type and job title against the scope."),
                    ],
                    bullets=[
                        _("Employment type (In-house, Freelancer, Vendor, …) must be linked to this scope in Employment structure."),
                        _("Job title must also be linked to this scope in the job titles workspace."),
                        _("Client / Guest can include non-employees when their employment type is Client/Guest (or linked to that scope)."),
                        _("If policy blocks an add, a toast explains the conflict (for example employment type not allowed for Offline Editing)."),
                        _("Only accounts with project team manage permission see Manage; others can view the roster but not change it."),
                    ],
                    note=_("Job titles are the “roles” you assign people in the directory. On Team they show under each name. Task assignment is limited to people already on the project team."),
                ),
            ],
        ),
        "project-editing-item": page(
            _("Editing Item"),
            _("TV series episode dock — every episode and collection with runtime, scenes, scripts, and shoot / sync / 1st-edit progress."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What this page is for"),
                    paragraphs=[
                        _("Editing Item (page title: Editing elements) is the TV-series episode workspace. It answers: which episodes exist, how long they run, how many scenes they have, whether a script is attached, and how far shoot / sync / first edit have progressed."),
                        _("An editing item in the pipeline sense is a deliverable such as EP01. On this page each Episode card links to its pipeline code (EP01, EP02…) and status. Full department tracking lives in Post Pipeline; this page is the editorial map of episodes and collections."),
                    ],
                    shots=[
                        shot(
                            "project-editing-item.png",
                            _("Editing Item page"),
                            _("Editing Item: Collections (Episode X, Establishing Shot) and the Episodes grid."),
                        )
                    ],
                    note=_("This tab appears only on TV series projects. Feature films and commercials use other planning patterns (reels / copies) via Post Pipeline."),
                ),
                section(
                    "meaning",
                    _("What “Editing Item” means"),
                    paragraphs=[
                        _("In production language, an editing item is the unit editors and departments work against — usually one episode (EP01)."),
                        _("On this page:"),
                    ],
                    bullets=[
                        _("Episode 1, Episode 2, … are the numbered editorial units of the series."),
                        _("EP01 / EP02 badges are the linked Post Pipeline deliverable codes and their overall status (Not Started, Color In Progress, …)."),
                        _("Episode X holds production items not yet assigned to a numbered episode."),
                        _("Establishing Shot is a collection of establishing shots across shooting days."),
                    ],
                ),
                section(
                    "collections",
                    _("Collections"),
                    paragraphs=[
                        _("Above the episode grid, Collections catch work that is not a normal numbered episode."),
                    ],
                    dl=[
                        (
                            _("Episode X"),
                            _("Unassigned production items / scenes that still need an episode number. Open it to sort material into episodes."),
                        ),
                        (
                            _("Establishing Shot"),
                            _("All establishing shots across shooting days, managed as one collection."),
                        ),
                        (
                            _("Open (pop-out) control"),
                            _("Opens the collection detail page."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-editing-item-collections.png",
                            _("Collections and episode cards"),
                            _("Collections row plus episode cards with combo progress charts."),
                        )
                    ],
                ),
                section(
                    "episode-card",
                    _("Episode card — every element"),
                    paragraphs=[
                        _("Each numbered episode is a dock card. Click the title or the open icon to enter episode detail (scenes, takes, assignments)."),
                    ],
                    dl=[
                        (
                            _("Title (Episode N)"),
                            _("Opens the episode detail workspace."),
                        ),
                        (
                            _("Runtime chip (clock)"),
                            _("Episode runtime from selected scene takes. “Runtime selection needed” appears when takes still need choosing."),
                        ),
                        (
                            _("Scenes chip (camera)"),
                            _("Original scenes that belong to this episode. A +N assigned chip means scenes moved in from other episodes."),
                        ),
                        (
                            _("Reshoot chip"),
                            _("Shown when reshoot versions exist for scenes on this episode."),
                        ),
                        (
                            _("EP0N · status link"),
                            _("Linked Post Pipeline deliverable. Opens that item’s pipeline status (for example Color In Progress). If missing, Sync episode repairs the link."),
                        ),
                        (
                            _("Script line"),
                            _("Pages / scenes from an uploaded PDF, or a prompt to upload a script."),
                        ),
                        (
                            _("Upload script / View script"),
                            _("Attach or open the episode PDF. The ⋯ menu offers Replace, Show in Finder (desktop), and Remove."),
                        ),
                        (
                            _("Open icon"),
                            _("Same as opening the episode — jumps to episode detail."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-editing-item-card.png",
                            _("Single episode card"),
                            _("Episode card: runtime, scenes, EP status, script prompt, and progress chart."),
                        )
                    ],
                ),
                section(
                    "chart",
                    _("Progress chart (shoot / sync / 1st edit)"),
                    paragraphs=[
                        _("The circular graph is a three-ring combo chart. The center label highlights one ring (often SYNC or 1ST). The legend under the chart lists all three percentages."),
                    ],
                    dl=[
                        (
                            _("% shoot"),
                            _("How much of this episode’s effective scenes are shot."),
                        ),
                        (
                            _("% sync"),
                            _("How far sync / dailies work has progressed for the episode’s material."),
                        ),
                        (
                            _("% 1st edit"),
                            _("How far first-cut / first edit work has progressed."),
                        ),
                    ],
                    bullets=[
                        _("Rings fill as each percentage rises (0% empty → 100% full)."),
                        _("Use the chart to spot episodes stuck before sync or first edit while others are complete."),
                    ],
                ),
                section(
                    "related",
                    _("Related pages"),
                    bullets=[
                        _("Shooting days — where scenes are scheduled and marked shot."),
                        _("Post Pipeline — department chips, versions, delivery for EP01… deliverables."),
                        _("VFX Portal / Color Portal — department work for the same episodes."),
                        _("Team — who can be assigned editorial tasks on this project."),
                    ],
                ),
            ],
        ),
        "project-shooting-days": page(
            _("Shooting days"),
            _("Production calendar by unit — open a day to log scenes, sync / 1st-edit progress, VFX flags, and day notes."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What this page is for"),
                    paragraphs=[
                        _("Shooting days (Production) is the set calendar for the project. It answers: which days were shot, how far sync and first edit have progressed per day, which HDD holds the media, and what scenes / plates / sound were logged."),
                        _("Open a day card to add shooting items (scenes, reshoots, VFX slates, establishing shots, sound, …), mark Sync / 1st Edit / Needs VFX, and track day-level notes — including critical issues that can surface on the Dashboard."),
                    ],
                    shots=[
                        shot(
                            "project-shooting-days.png",
                            _("Shooting days list"),
                            _("Unit groups with day cards: Sync/1st donuts, HDD labels, and totals."),
                        )
                    ],
                    note=_("Workflow tab label is “Shooting days”; the URL path is /projects/…/production."),
                ),
                section(
                    "list",
                    _("Day list — search and units"),
                    paragraphs=[
                        _("Days are grouped by production unit. Use search to find days that contain a given episode, scene, or location."),
                    ],
                    dl=[
                        (
                            _("Search mode"),
                            _("Episode #, Scene #, or Location — then type in the query field."),
                        ),
                        (
                            _("Unit group"),
                            _("Collapsible block (e.g. Unit 1) with a count of shooting days."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-shooting-days-search.png",
                            _("Day search"),
                            _("Filter days by episode, scene, or location."),
                        )
                    ],
                ),
                section(
                    "card",
                    _("Day card — every element"),
                    paragraphs=[
                        _("Each card is one shooting day. Click it to open the day workspace."),
                    ],
                    dl=[
                        (
                            _("Day name + date"),
                            _("e.g. Day 1 · 2026-04-08."),
                        ),
                        (
                            _("Donut (Sync / 1st)"),
                            _("Outer ring = % of items with Sync done; inner ring = % with first edit done. Center shows Sync %."),
                        ),
                        (
                            _("Sync / 1st legend"),
                            _("Same percentages as the rings, spelled out under the chart."),
                        ),
                        (
                            _("HDD"),
                            _("Linked Machine Room backup volume label when the day is attached to a disk."),
                        ),
                        (
                            _("Total"),
                            _("Sum of scene durations (M:SS) plus any legacy shot-log time for the day."),
                        ),
                    ],
                ),
                section(
                    "day",
                    _("Inside a day — dashboard"),
                    paragraphs=[
                        _("The day page opens with location, summary stats, and the Sync/1st donut for that day only."),
                    ],
                    dl=[
                        (
                            _("Location"),
                            _("Set / save the shooting location for the day (suggestions from other days)."),
                        ),
                        (
                            _("Items"),
                            _("Count of shooting rows, broken into scenes · VFX · sound."),
                        ),
                        (
                            _("Shot duration"),
                            _("Total duration logged for the day."),
                        ),
                        (
                            _("Sync / 1st donut"),
                            _("Same meaning as on the list card, for this day."),
                        ),
                        (
                            _("Episode X items"),
                            _("Rows still assigned to Episode X (unassigned) instead of a numbered episode."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-shooting-days-dashboard.png",
                            _("Day dashboard"),
                            _("Location, items, shot duration, Sync/1st, and Episode X counts."),
                        ),
                        shot(
                            "project-shooting-days-day.png",
                            _("Day workspace"),
                            _("Full day: dashboard, filters, shooting item rows, and Day notes."),
                        ),
                    ],
                ),
                section(
                    "items",
                    _("Shooting items"),
                    paragraphs=[
                        _("Each row is something shot or logged that day. Filter by type, or switch List / Cards layout."),
                    ],
                    dl=[
                        (
                            _("Filters"),
                            _("All, Scenes, VFX, Sound, Establishing Shot, Technical, Episode X, Critical."),
                        ),
                        (
                            _("List / Cards"),
                            _("Compact rows vs card grid for the same items."),
                        ),
                        (
                            _("Episode + Scene"),
                            _("TV series: episode badge (Ep 02…) links to episode detail; scene label and duration."),
                        ),
                        (
                            _("Sync / 1st Edit / Needs VFX"),
                            _("Per-row progress. Needs VFX feeds the VFX Portal when the row is included there."),
                        ),
                        (
                            _("In VFX"),
                            _("Badge when the scene is live in VFX Management with Needs VFX on."),
                        ),
                        (
                            _("Runtime Take"),
                            _("Which version of a scene (original vs reshoot) counts toward episode runtime."),
                        ),
                        (
                            _("Add shooting item"),
                            _("Opens a form: type (Scene, Reshoot, VFX Slate, Establishing Shot, …), episode, scene/description, duration, Sync / 1st Edit / Needs VFX, optional note and thumbnail."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-shooting-days-filters.png",
                            _("Item filters"),
                            _("Type filters and List / Cards layout toggle."),
                        ),
                        shot(
                            "project-shooting-days-items.png",
                            _("Item rows"),
                            _("Scene rows with Sync, 1st Edit, VFX, and runtime badges."),
                        ),
                    ],
                ),
                section(
                    "notes",
                    _("Day notes"),
                    paragraphs=[
                        _("Day-level notes sit under the item list. Mark a note Critical so it can surface as a production alert (including on the Dashboard when it affects you). Solve moves it out of the open list."),
                    ],
                    dl=[
                        (
                            _("Open notes"),
                            _("Active day notes; Critical badge when flagged."),
                        ),
                        (
                            _("Solved"),
                            _("Resolved notes kept for history under the open list."),
                        ),
                        (
                            _("vs scene Critical"),
                            _("Day notes are separate from a Critical badge on an individual scene row."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-shooting-days-notes.png",
                            _("Day notes"),
                            _("Day-level notes area under the shooting items list."),
                        )
                    ],
                ),
                section(
                    "related",
                    _("Related pages"),
                    bullets=[
                        _("Editing Item — episode map fed by these scene rows (shoot / sync / 1st edit)."),
                        _("VFX Portal — scenes marked Needs VFX / In VFX."),
                        _("Machine Room — HDD links and ingest for shooting-day media."),
                        _("Dashboard — critical shooting-day notes that need your attention."),
                    ],
                ),
            ],
        ),
        "project-vfx-portal": page(
            _("VFX Portal"),
            _("VFX shots, review, and delivery for this project — scenes tree, preview markers, shot briefing, and version review."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What this page is for"),
                    paragraphs=[
                        _("VFX Portal is the project-level VFX workspace. It answers: which episodes and scenes need VFX, which shots exist, what was sent / is in review / approved / delivered, and how to brief and review versions."),
                        _("Studio-wide VFX Department is separate — use it when you work across many projects at once. This tab stays inside one show."),
                    ],
                    shots=[
                        shot(
                            "project-vfx-portal.png",
                            _("VFX Portal workspace"),
                            _("Three columns: Scenes tree, Edits & shots preview, Review inspector."),
                        )
                    ],
                    note=_("Open a project → VFX Portal. TV series organize scenes under episode folders (Eps01…)."),
                ),
                section(
                    "toolbar",
                    _("Workspace toolbar"),
                    paragraphs=[
                        _("The top row controls layout focus and sharing / reporting."),
                    ],
                    dl=[
                        (
                            _("Default / Focus review / Focus timeline / Focus inspector / Focus compare"),
                            _("Layout modes that enlarge the panel you need (review, timeline, inspector, or version compare)."),
                        ),
                        (
                            _("Full screen"),
                            _("Expands the VFX workspace to fill the browser window."),
                        ),
                        (
                            _("Create review link…"),
                            _("Creates a secure client/director review URL — no studio login required."),
                        ),
                        (
                            _("Generate PDF report…"),
                            _("Builds a PDF of selected episodes, scenes, and shots (optional ref frames, comments, versions)."),
                        ),
                        (
                            _("Show Progress sheet"),
                            _("Opens a scene-by-scene VFX progress overview for the project."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-vfx-portal-toolbar.png",
                            _("Toolbar"),
                            _("Focus modes plus Full screen, review link, PDF report, and Progress sheet."),
                        )
                    ],
                ),
                section(
                    "scenes",
                    _("Scenes panel (left)"),
                    paragraphs=[
                        _("The left tree is the episode → scene hierarchy for VFX work."),
                    ],
                    dl=[
                        (
                            _("All / In Review"),
                            _("Filter scenes: everything, or only scenes with shots currently in review."),
                        ),
                        (
                            _("Episode folder (Eps01…)"),
                            _("Groups production scenes for that episode. + adds a scene; swap moves a scene to another episode."),
                        ),
                        (
                            _("Scene row"),
                            _("Shows shot count. Select a scene to load its preview, markers, and shot list in the center."),
                        ),
                    ],
                ),
                section(
                    "mid",
                    _("Edits & shots (center)"),
                    paragraphs=[
                        _("With a scene selected you get the scene preview, stats, markers, and shot creation tools."),
                    ],
                    dl=[
                        (
                            _("Scene preview"),
                            _("Play the scene reel/preview. Upload Preview if none exists yet."),
                        ),
                        (
                            _("Shot summary stats"),
                            _("Counts for shots, review, approved, blocked, pending, and in-house vs external."),
                        ),
                        (
                            _("Add Marker"),
                            _("Marks a timecode on the preview where a VFX shot is needed."),
                        ),
                        (
                            _("Create Shot"),
                            _("Turns the selected marker into a named VFX shot (e.g. Eps01_Scene16_Shot06)."),
                        ),
                        (
                            _("Marker / shot cards"),
                            _("Thumbnails under the player. Click one to load that shot in Review."),
                        ),
                        (
                            _("Scene Board (at root)"),
                            _("When Root is selected, the board lists scenes with Needs VFX / In Review filters and Shots → Sent → Review → Approved → Delivered bars."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-vfx-portal-scene.png",
                            _("Scene selected"),
                            _("Preview player, marker cards, and Review panel for a shot."),
                        )
                    ],
                ),
                section(
                    "review",
                    _("Review panel (right)"),
                    paragraphs=[
                        _("Select a shot to inspect reference, briefing, versions, vendor, priority, and pipeline actions."),
                    ],
                    dl=[
                        (
                            _("Reference frame"),
                            _("Still used as the visual brief for the shot."),
                        ),
                        (
                            _("Shot briefing"),
                            _("Director / VFX notes. Toggle whether the briefing is included in PDF export."),
                        ),
                        (
                            _("Version review"),
                            _("Version tabs, media player, comments, and Compare versions."),
                        ),
                        (
                            _("Vendor / Priority"),
                            _("In-house vs external (with vendor name) and shot priority."),
                        ),
                        (
                            _("Pipeline status + Send / Recall / Block / Approve"),
                            _("Move the shot through send → review → approve (or block / recall when allowed)."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-vfx-portal-review.png",
                            _("Review inspector"),
                            _("Shot code, reference frame, briefing, and version review area."),
                        )
                    ],
                ),
                section(
                    "related",
                    _("Related pages"),
                    bullets=[
                        _("Editing Item — episode map and shoot / sync / 1st-edit progress."),
                        _("Post Pipeline — deliverable status across departments."),
                        _("Color Portal — color handoff for the same EP01… items."),
                        _("VFX Department — cross-project VFX hub."),
                    ],
                ),
            ],
        ),
        "project-color-portal": page(
            _("Color Portal"),
            _("Color handoff and tracking for every editing item — filters, dock cards, and per-item Color Workspace."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What this page is for"),
                    paragraphs=[
                        _("Color Portal is the project overview of color work. Each card is an editing item (usually EP01, EP02…) with edit/VFX readiness, handling, color status, colorist, due date, and latest grade version."),
                        _("Open Color Workspace on a card for handoff, conform, grade versions, gallery, notes, and deliveries. Studio-wide Color Department is separate for cross-project boards."),
                    ],
                    shots=[
                        shot(
                            "project-color-portal.png",
                            _("Color Portal overview"),
                            _("Filters, pipeline summary counts, and episode dock cards."),
                        )
                    ],
                    note=_("Header links: Post Pipeline (manage which items need color) and Department board (when in-house color is enabled)."),
                ),
                section(
                    "filters",
                    _("Filters and summary"),
                    paragraphs=[
                        _("Use the filter row to narrow the dock. Summary chips show pipeline totals at a glance."),
                    ],
                    dl=[
                        (
                            _("Search"),
                            _("Match editing-item code or title."),
                        ),
                        (
                            _("Type"),
                            _("Episode, reel, copy, etc."),
                        ),
                        (
                            _("Color status"),
                            _("Not started, waiting materials, ready, sent, in progress, reviews, revision, approved, blocked, …"),
                        ),
                        (
                            _("Handling"),
                            _("In-house, external vendor, client-side, not required, or unknown."),
                        ),
                        (
                            _("Colorist"),
                            _("Filter to items assigned to a specific colorist."),
                        ),
                        (
                            _("Show not required"),
                            _("Include items marked not required for color (normally hidden)."),
                        ),
                        (
                            _("Summary chips"),
                            _("Counts: in color pipeline, in progress, approved, blocked (and not-required when shown)."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-color-portal-filters.png",
                            _("Filter row"),
                            _("Search, type, status, handling, colorist, and Show not required."),
                        )
                    ],
                ),
                section(
                    "card",
                    _("Editing-item card — every element"),
                    paragraphs=[
                        _("Each dock card is one Post Pipeline deliverable in the color lane."),
                    ],
                    dl=[
                        (
                            _("Code + type badge"),
                            _("e.g. EP01 · Episode. Linked Episode N ties it to Editing Item."),
                        ),
                        (
                            _("No handoff/guide uploaded"),
                            _("Warning when color still needs a handoff package or guide video before send."),
                        ),
                        (
                            _("Edit / VFX"),
                            _("Upstream edit and VFX status so you know readiness."),
                        ),
                        (
                            _("Handling"),
                            _("Who grades this item (in-house, vendor, client, …)."),
                        ),
                        (
                            _("Color status"),
                            _("Where this item sits in the color pipeline (e.g. Sent)."),
                        ),
                        (
                            _("Colorist / Due / Latest color"),
                            _("Assignee, due date, and newest uploaded grade version label."),
                        ),
                        (
                            _("Open Color Workspace"),
                            _("Opens the full item workspace (Handoff, Conform, Grade Versions, Gallery, …)."),
                        ),
                        (
                            _("Color / Upload / Note (when permitted)"),
                            _("Quick actions: update route (required, handling, status, colorist, vendor, due, notes), upload a grade version, or add a timecoded note."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-color-portal-card.png",
                            _("Single color card"),
                            _("EP01 card with status grid and Open Color Workspace."),
                        )
                    ],
                ),
                section(
                    "workspace",
                    _("Color Workspace (per item)"),
                    paragraphs=[
                        _("From Open Color Workspace you work one editing item end-to-end."),
                    ],
                    dl=[
                        (
                            _("Handoff"),
                            _("Grade mode, picture lock, linked edit, VFX readiness, colorist/supervisor, due, priority, and picture delivery specs. VFX shot list for context."),
                        ),
                        (
                            _("Conform"),
                            _("Conform request and status for the handoff package."),
                        ),
                        (
                            _("Grade Versions"),
                            _("Uploaded color versions and notes."),
                        ),
                        (
                            _("Gallery / Review Notes / Deliveries / Activity"),
                            _("Stills gallery, review notes, delivery tracking, and activity history."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-color-portal-workspace.png",
                            _("Color Workspace — Handoff"),
                            _("EP01 workspace: readiness fields and VFX shots context."),
                        )
                    ],
                ),
                section(
                    "related",
                    _("Related pages"),
                    bullets=[
                        _("Post Pipeline — mark items for color and manage deliverables."),
                        _("Editing Item — episode map for the same EP codes."),
                        _("VFX Portal — shot progress that feeds VFX readiness."),
                        _("Color Department — cross-project color boards."),
                    ],
                ),
            ],
        ),
        "project-audio-library": page(
            _("Audio Library"),
            _("Project-scoped libraries and linked music folders — browse show audio without leaving the production."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What this page is for"),
                    paragraphs=[
                        _("Inside a project, Audio Library is the show’s own audio shelf: sub-libraries you create here, plus folders linked from the global studio Audio Library."),
                        _("It is not the global library (sidebar → Audio Library). Global indexing and folder linking happen there; this page consumes those links for one production."),
                    ],
                    shots=[
                        shot(
                            "project-audio-library.png",
                            _("Project Audio Library"),
                            _("Libraries tree, file list, and inspector for a linked music folder."),
                        )
                    ],
                    note=_("Lead text on the page: libraries and linked folders on the left; files load in the center. Link folders from the global Audio Library."),
                ),
                section(
                    "layout",
                    _("Three-panel layout"),
                    dl=[
                        (
                            _("Libraries (left)"),
                            _("Tree of Main, nested sub-libraries, and linked folders. Collapse the panel with ⟨ when you need space."),
                        ),
                        (
                            _("Files (center)"),
                            _("Tracks in the selected library or linked folder — play, favorite, color-tag, duration."),
                        ),
                        (
                            _("Inspector (right)"),
                            _("Selected file: duration, type, full path, Copy path, Show in Finder."),
                        ),
                    ],
                ),
                section(
                    "libraries",
                    _("Libraries tree"),
                    paragraphs=[
                        _("Organize show audio under Main, then nest sub-libraries and drop linked folders into them."),
                    ],
                    dl=[
                        (
                            _("Main"),
                            _("Root library for the project. Drop libraries here for top level, or onto another library to nest."),
                        ),
                        (
                            _("New sub-library… (when permitted)"),
                            _("Creates a nested library under the current parent (e.g. Music under Main)."),
                        ),
                        (
                            _("Linked folder (📁)"),
                            _("A folder indexed in the global Audio Library and linked into this project. Selecting it loads its files in the center."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-audio-library-tree.png",
                            _("Libraries panel"),
                            _("Main → Music with linked folders (A House of Dynamite, Bird Box)."),
                        )
                    ],
                ),
                section(
                    "toolbar",
                    _("Toolbar and filters"),
                    dl=[
                        (
                            _("Breadcrumb"),
                            _("Current path (e.g. Music / A House of Dynamite) and file count."),
                        ),
                        (
                            _("Filter files…"),
                            _("Narrow the loaded list by filename."),
                        ),
                        (
                            _("Favorites (🤍)"),
                            _("Show only favorited tracks."),
                        ),
                        (
                            _("Color dots"),
                            _("Filter by color tag (red → purple)."),
                        ),
                    ],
                ),
                section(
                    "files",
                    _("Files and inspector"),
                    paragraphs=[
                        _("Select a file in the center list to fill the inspector."),
                    ],
                    dl=[
                        (
                            _("Play / favorite / color tags"),
                            _("Preview audio, mark favorites, and apply color tags used by the filters."),
                        ),
                        (
                            _("Copy path / Show in Finder"),
                            _("Copy the volume path or reveal the file on the desktop Mac (when mounted)."),
                        ),
                        (
                            _("Link from global Audio Library"),
                            _("In the global library inspector, link an indexed folder into this project so it appears in the left tree."),
                        ),
                    ],
                    shots=[
                        shot(
                            "project-audio-library-inspector.png",
                            _("Inspector"),
                            _("Selected track metadata, path, and Copy path / Show in Finder."),
                        )
                    ],
                ),
                section(
                    "related",
                    _("Related pages"),
                    bullets=[
                        _("Audio Library (global) — index mounts and link folders into projects."),
                        _("Project Team — who can manage project audio libraries."),
                        _("Post Pipeline / Editing Item — editorial context for the same show."),
                    ],
                ),
            ],
        ),
        "project-post-pipeline": page(
            _("Post Pipeline"),
            _("Post status across editorial and finishing for the show."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Post Pipeline visualizes where editorial and finishing stand — a status board for the production’s post path."),
                    ],
                    shots=[
                        shot(
                            "project-post-pipeline.png",
                            _("Post Pipeline"),
                            _("Post Pipeline: editorial and finishing status."),
                        )
                    ],
                ),
            ],
        ),
        "project-settings": page(
            _("Settings"),
            _("Project configuration — available when your role can manage the show."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Project Settings holds configuration for the production (type, defaults, and management options). Not every member can open this tab."),
                    ],
                    shots=[
                        shot(
                            "project-settings.png",
                            _("Project Settings"),
                            _("Settings: project configuration for managers."),
                        )
                    ],
                ),
            ],
        ),
        "project-working-hours": page(
            _("Working Hours"),
            _("Logged time against this production."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Working Hours records actual time spent on the project. Dashboard session controls often deep-link here for today’s work."),
                    ],
                    shots=[
                        shot(
                            "project-working-hours.png",
                            _("Working Hours"),
                            _("Working Hours: time logged on the production."),
                        )
                    ],
                ),
            ],
        ),
        "project-log-book": page(
            _("Log Book"),
            _("Project activity and notes log."),
            open_endpoint="projects_list",
            open_label=_("Open Projects"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Log Book is a chronological activity and notes trail for the production — useful for handoffs and history."),
                    ],
                    shots=[
                        shot(
                            "project-log-book.png",
                            _("Log Book"),
                            _("Log Book: project activity history."),
                        )
                    ],
                ),
            ],
        ),
        # Departments
        "vfx-department": page(
            _("VFX Department"),
            _("Cross-project VFX department workspace."),
            open_endpoint="vfx_department_home",
            open_label=_("Open VFX Department"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("VFX Department aggregates VFX work across shows for artists and supervisors. Use a project’s VFX Portal when you need that show only."),
                    ],
                    shots=[
                        shot(
                            "vfx-department.png",
                            _("VFX Department"),
                            _("VFX Department hub across projects."),
                        )
                    ],
                ),
            ],
        ),
        "color-department": page(
            _("Color Department"),
            _("Cross-project color department workspace."),
            open_endpoint="color_department_home",
            open_label=_("Open Color Department"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Color Department is the studio-wide color hub. Project Color Portal stays focused on one production."),
                    ],
                    shots=[
                        shot(
                            "color-department.png",
                            _("Color Department"),
                            _("Color Department hub across projects."),
                        )
                    ],
                ),
            ],
        ),
        # Admin
        "users": page(
            _("Users"),
            _("Directory, roles, and account management."),
            open_endpoint="users_list",
            open_label=_("Open Users"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Users is the admin directory of accounts and directory users. Approve, edit roles, and manage membership from here."),
                    ],
                    shots=[
                        shot(
                            "users.png",
                            _("Users directory"),
                            _("Users: studio directory and account cards."),
                        )
                    ],
                ),
            ],
        ),
        "approvals": page(
            _("Approvals"),
            _("Pending users, role changes, and access requests."),
            open_endpoint="admin_approvals",
            open_label=_("Open Approvals"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Approvals queues new accounts, role changes, reactivations, and permission requests for administrators."),
                    ],
                    shots=[
                        shot(
                            "approvals.png",
                            _("Approvals queue"),
                            _("Approvals: pending access and role requests."),
                        )
                    ],
                ),
            ],
        ),
        "task-management": page(
            _("Task management"),
            _("Presets, titles, scopes, and task configuration."),
            open_endpoint="control_panel",
            open_label=_("Open Task management"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Task management (Control Panel) configures how tasks are titled, grouped, and scoped across the studio."),
                    ],
                    shots=[
                        shot(
                            "task-management.png",
                            _("Task management"),
                            _("Task management: presets and scopes."),
                        )
                    ],
                ),
            ],
        ),
        "access-control": page(
            _("Access Control"),
            _("Permissions for roles, job titles, and per-user exceptions. Default is deny unless granted."),
            open_endpoint="control_access_control",
            open_label=_("Open Access Control"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Access Control is the studio permission manager. Use it to decide which roles and job titles can view or change each part of the app, then add per-person exceptions when needed."),
                        _("Open it from Admin → Access Control. The sidebar switches Pages, Actions, Role permissions, Job title permissions, User overrides, Permission preview, and Help."),
                    ],
                    shots=[
                        shot(
                            "ac-help-overview.png",
                            _("Access Control overview"),
                            _("Access Control: sidebar plus the Pages catalog."),
                            folder="img/access-control-help",
                        )
                    ],
                    note=_("A longer illustrated guide lives under Access Control → Help."),
                ),
                section(
                    "how-it-decides",
                    _("How access is decided"),
                    paragraphs=[
                        _("When someone opens a page or tries an action, grants are checked in this order: user override, then job title, then role. If nothing granted the action, it is blocked."),
                    ],
                    bullets=[
                        _("User override — Allow or Deny for one person on one page + action. This wins."),
                        _("Job title — grants attached to the directory job title."),
                        _("Role — grants attached to the account role (Administrator, Producer, Editor, …)."),
                        _("Default deny — no grant means no access."),
                    ],
                ),
                section(
                    "pages",
                    _("Pages"),
                    paragraphs=[
                        _("Pages are the modules you can protect. Each card shows the name, a colored module badge, the stable key, the route, and a short description. Search filters by name, key, or module."),
                    ],
                    shots=[
                        shot(
                            "ac-help-pages.png",
                            _("Pages catalog"),
                            _("Pages: cards with colored module badges (admin, core, production, VFX, color, and more)."),
                            folder="img/access-control-help",
                        )
                    ],
                ),
                section(
                    "actions",
                    _("Actions"),
                    paragraphs=[
                        _("Actions are the verbs you can grant: View, Create, Edit, Delete, Upload, Approve, and specialized ones (Machine Room copy, VFX shots, and so on). Role and job-title matrices use the common verbs; this catalog lists every verb."),
                    ],
                    shots=[
                        shot(
                            "ac-help-actions.png",
                            _("Actions catalog"),
                            _("Actions: each verb has a display name, key, and description."),
                            folder="img/access-control-help",
                        )
                    ],
                ),
                section(
                    "roles",
                    _("Role permissions"),
                    paragraphs=[
                        _("Pick a role, then turn action chips on or off per page. Clicking a chip marks unsaved changes; press Save changes in the header before leaving."),
                    ],
                    shots=[
                        shot(
                            "ac-help-roles.png",
                            _("Role permission matrix"),
                            _("Role permissions: Administrator matrix with action chips per page."),
                            folder="img/access-control-help",
                        )
                    ],
                ),
                section(
                    "job-titles",
                    _("Job title permissions"),
                    paragraphs=[
                        _("Same matrix as roles, keyed to a directory job title. Title grants stack with role grants unless a user override says otherwise."),
                    ],
                    shots=[
                        shot(
                            "ac-help-job-titles.png",
                            _("Job title permission matrix"),
                            _("Job title permissions: select a title, then grant chips and save."),
                            folder="img/access-control-help",
                        )
                    ],
                ),
                section(
                    "overrides",
                    _("User overrides"),
                    paragraphs=[
                        _("Overrides are exceptions for one person. They beat both role and job title. Add override applies immediately; there is no extra Save on this screen."),
                    ],
                    shots=[
                        shot(
                            "ac-help-overrides.png",
                            _("User overrides"),
                            _("User overrides: user, page, action, Allow or Deny, optional note."),
                            folder="img/access-control-help",
                        )
                    ],
                ),
                section(
                    "preview",
                    _("Permission preview"),
                    paragraphs=[
                        _("Preview shows effective access for one person after role, job title, and overrides are combined. Hover a badge to see where the grant came from."),
                    ],
                    shots=[
                        shot(
                            "ac-help-preview.png",
                            _("Permission preview"),
                            _("Permission preview: effective view and action badges for the selected person."),
                            folder="img/access-control-help",
                        )
                    ],
                ),
            ],
        ),
        "task-log": page(
            _("Task Log"),
            _("Operational log of task activity."),
            open_endpoint="admin_task_log",
            open_label=_("Open Task Log"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Task Log is an admin operational view of task status changes and related activity."),
                    ],
                    shots=[
                        shot(
                            "task-log.png",
                            _("Task Log"),
                            _("Task Log: operational task history."),
                        )
                    ],
                ),
            ],
        ),
        "notification-management": page(
            _("Notification Management"),
            _("Rules that drive in-app and email alerts."),
            open_endpoint="admin_notification_management",
            open_label=_("Open Notification Management"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Notification Management configures rules for when the app notifies people (critical notes, assignments, storage, and more)."),
                    ],
                    shots=[
                        shot(
                            "notification-management.png",
                            _("Notification Management"),
                            _("Notification Management: alert rules."),
                        )
                    ],
                ),
            ],
        ),
        "notification-log": page(
            _("Notification log"),
            _("History of sent notifications."),
            open_endpoint="admin_notification_log",
            open_label=_("Open Notification log"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Notification log shows what was sent, to whom, and when — useful for debugging alert rules."),
                    ],
                    shots=[
                        shot(
                            "notification-log.png",
                            _("Notification log"),
                            _("Notification log: delivery history."),
                        )
                    ],
                ),
            ],
        ),
        "employment-structure": page(
            _("Employment structure"),
            _("Jobs, departments, and org structure."),
            open_endpoint="control_employment_structure",
            open_label=_("Open Employment structure"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Employment structure defines job titles and organizational groupings used across users and permissions."),
                    ],
                    shots=[
                        shot(
                            "employment-structure.png",
                            _("Employment structure"),
                            _("Employment structure: jobs and departments."),
                        )
                    ],
                ),
            ],
        ),
        "edit-suites": page(
            _("Edit suites"),
            _("Rooms available for booking."),
            open_endpoint="control_edit_suites",
            open_label=_("Open Edit suites"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Edit suites configures the physical or virtual rooms that appear in Booking."),
                    ],
                    shots=[
                        shot(
                            "edit-suites.png",
                            _("Edit suites"),
                            _("Edit suites: rooms used by Booking."),
                        )
                    ],
                ),
            ],
        ),
        "app-workflow": page(
            _("APP WorkFlow"),
            _("Documented application workflows."),
            open_endpoint="control_app_workflow",
            open_label=_("Open APP WorkFlow"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("APP WorkFlow documents how the studio expects people to move through the application for common jobs."),
                    ],
                    shots=[
                        shot(
                            "app-workflow.png",
                            _("APP WorkFlow"),
                            _("APP WorkFlow: documented studio processes."),
                        )
                    ],
                ),
            ],
        ),
        "updates": page(
            _("Updates"),
            _("What’s New posts for the team."),
            open_endpoint="updates_page",
            open_label=_("Open Updates"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Updates is where administrators publish What’s New items that can appear on the Dashboard."),
                    ],
                    shots=[
                        shot(
                            "updates.png",
                            _("Updates"),
                            _("Updates: What’s New posts."),
                        )
                    ],
                ),
            ],
        ),
        "system-setup": page(
            _("System Setup"),
            _("Seeds and system bootstrap tools."),
            open_endpoint="control_system_setup",
            open_label=_("Open System Setup"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("System Setup holds administrative bootstrap and seed tools for a new or reset environment. Use carefully."),
                    ],
                    shots=[
                        shot(
                            "system-setup.png",
                            _("System Setup"),
                            _("System Setup: bootstrap and seed tools."),
                        )
                    ],
                ),
            ],
        ),
        "news-sources": page(
            _("News sources"),
            _("Feeds that power Industry Radar."),
            open_endpoint="control_industry_news_sources",
            open_label=_("Open News sources"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("News sources configure where Industry Radar content comes from."),
                    ],
                    shots=[
                        shot(
                            "news-sources.png",
                            _("News sources"),
                            _("News sources: feeds for Industry Radar."),
                        )
                    ],
                ),
            ],
        ),
        "industry-news": page(
            _("Industry news"),
            _("Curate and publish industry items."),
            open_endpoint="control_industry_news",
            open_label=_("Open Industry news"),
            sections=[
                section(
                    "overview",
                    _("What it does"),
                    paragraphs=[
                        _("Industry news is the admin editor for Radar items — publish, edit, or retire stories the team sees."),
                    ],
                    shots=[
                        shot(
                            "industry-news.png",
                            _("Industry news admin"),
                            _("Industry news: curate Radar items."),
                        )
                    ],
                ),
            ],
        ),
    }


TOUR_HELP_SLUGS = frozenset(
    {
        "dashboard",
        "industry-radar",
        "chat",
        "audio-library",
        "notes",
        "storage",
        "machine-room",
        "machine-room-help",
        "tasks",
        "projects",
        "booking",
        "producer-hunt",
        "profile",
        "project-overview",
        "project-team",
        "project-editing-item",
        "project-shooting-days",
        "project-vfx-portal",
        "project-color-portal",
        "project-audio-library",
        "project-post-pipeline",
        "project-settings",
        "project-working-hours",
        "project-log-book",
        "vfx-department",
        "color-department",
        "users",
        "approvals",
        "task-management",
        "access-control",
        "task-log",
        "notification-management",
        "notification-log",
        "employment-structure",
        "edit-suites",
        "app-workflow",
        "updates",
        "system-setup",
        "news-sources",
        "industry-news",
    }
)
