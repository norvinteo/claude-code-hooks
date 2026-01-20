#!/usr/bin/env python3
"""
Session Progress Dashboard - View and manage Claude Code hook session data.

Usage: python3 .claude/hooks/dashboard.py
Opens: http://localhost:8765

Features:
- Display all sessions with their plan state
- Show progress (completed/total items) per session
- Show costs per session
- Clear session button for each session
- Auto-refresh capability (5s interval)
"""

import json
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Configuration
PORT = 8765
HOOKS_DIR = Path(__file__).parent
SESSIONS_DIR = HOOKS_DIR / "sessions"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Session Dashboard</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }

        .header {
            text-align: center;
            padding: 20px 0 30px;
        }

        .header h1 {
            font-size: 2rem;
            font-weight: 600;
            background: linear-gradient(90deg, #00d9ff, #00ff88);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }

        .header .subtitle {
            color: #888;
            font-size: 0.9rem;
        }

        .controls {
            display: flex;
            justify-content: center;
            gap: 12px;
            margin-bottom: 24px;
            flex-wrap: wrap;
        }

        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }

        .btn-primary {
            background: linear-gradient(135deg, #00d9ff, #0099cc);
            color: white;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 217, 255, 0.3);
        }

        .btn-danger {
            background: linear-gradient(135deg, #ff4757, #cc0022);
            color: white;
        }

        .btn-danger:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(255, 71, 87, 0.3);
        }

        .btn-secondary {
            background: #2a2a4a;
            color: #e0e0e0;
            border: 1px solid #3a3a5a;
        }

        .btn-secondary:hover {
            background: #3a3a5a;
        }

        .stats-bar {
            display: flex;
            justify-content: center;
            gap: 40px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }

        .stat {
            text-align: center;
        }

        .stat-value {
            font-size: 1.8rem;
            font-weight: 700;
            color: #00d9ff;
        }

        .stat-value.cost {
            color: #00ff88;
        }

        .stat-label {
            font-size: 0.8rem;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .sessions-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
            gap: 20px;
            max-width: 1600px;
            margin: 0 auto;
        }

        .session-card {
            background: linear-gradient(145deg, #1e1e3f, #252550);
            border-radius: 16px;
            padding: 20px;
            border: 1px solid #3a3a5a;
            transition: all 0.2s ease;
        }

        .session-card:hover {
            border-color: #00d9ff;
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }

        .session-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 16px;
        }

        .session-name {
            font-size: 1.1rem;
            font-weight: 600;
            color: #fff;
            line-height: 1.3;
            flex: 1;
            margin-right: 12px;
        }

        .session-id {
            font-size: 0.7rem;
            color: #666;
            font-family: monospace;
            background: #1a1a2e;
            padding: 4px 8px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .session-id:hover {
            background: #2a2a4a;
            color: #00d9ff;
        }

        .progress-section {
            margin-bottom: 16px;
        }

        .progress-bar-container {
            background: #1a1a2e;
            border-radius: 8px;
            height: 8px;
            overflow: hidden;
            margin-bottom: 8px;
        }

        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #00d9ff, #00ff88);
            border-radius: 8px;
            transition: width 0.3s ease;
        }

        .progress-bar.complete {
            background: linear-gradient(90deg, #00ff88, #00cc66);
        }

        .progress-text {
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
        }

        .progress-count {
            color: #00d9ff;
            font-weight: 600;
        }

        .progress-percent {
            color: #888;
        }

        .cost-section {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px;
            background: #1a1a2e;
            border-radius: 8px;
            margin-bottom: 16px;
        }

        .cost-amount {
            font-size: 1.2rem;
            font-weight: 700;
            color: #00ff88;
        }

        .cost-label {
            font-size: 0.8rem;
            color: #888;
        }

        .tokens-info {
            font-size: 0.75rem;
            color: #666;
        }

        .items-list {
            max-height: 400px;
            overflow-y: auto;
            margin-bottom: 16px;
        }

        .item {
            display: flex;
            align-items: flex-start;
            padding: 8px 0;
            border-bottom: 1px solid #2a2a4a;
            font-size: 0.85rem;
        }

        .item:last-child {
            border-bottom: none;
        }

        .item-status {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            margin-right: 10px;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.7rem;
        }

        .item-status.completed {
            background: #00ff88;
            color: #000;
        }

        .item-status.in_progress {
            background: #ffcc00;
            color: #000;
            animation: pulse 1.5s infinite;
        }

        .item-status.pending {
            background: #3a3a5a;
            color: #888;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .item-text {
            flex: 1;
            color: #ccc;
        }

        .item-text.completed {
            color: #888;
            text-decoration: line-through;
        }

        .session-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 12px;
            border-top: 1px solid #2a2a4a;
        }

        .session-time {
            font-size: 0.75rem;
            color: #666;
        }

        .btn-clear {
            padding: 6px 12px;
            font-size: 0.8rem;
        }

        .auto-refresh-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            color: #888;
        }

        .refresh-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #00ff88;
        }

        .refresh-dot.paused {
            background: #666;
        }

        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #666;
        }

        .empty-state-icon {
            font-size: 4rem;
            margin-bottom: 16px;
        }

        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 6px;
        }

        ::-webkit-scrollbar-track {
            background: #1a1a2e;
            border-radius: 3px;
        }

        ::-webkit-scrollbar-thumb {
            background: #3a3a5a;
            border-radius: 3px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: #4a4a6a;
        }

        @media (max-width: 480px) {
            .sessions-grid {
                grid-template-columns: 1fr;
            }

            .stats-bar {
                gap: 20px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Claude Session Dashboard</h1>
        <p class="subtitle">Monitor and manage Claude Code hook sessions</p>
    </div>

    <div class="controls">
        <button class="btn btn-primary" onclick="refreshData()">Refresh Now</button>
        <button class="btn btn-secondary" id="autoRefreshBtn" onclick="toggleAutoRefresh()">
            Auto-refresh: ON
        </button>
        <button class="btn btn-danger" onclick="clearAllSessions()">Clear All Sessions</button>
    </div>

    <div class="stats-bar">
        <div class="stat">
            <div class="stat-value" id="totalSessions">0</div>
            <div class="stat-label">Plan Sessions</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="completedTasks">0</div>
            <div class="stat-label">Completed Tasks</div>
        </div>
        <div class="stat">
            <div class="stat-value cost" id="totalCost">$0.00</div>
            <div class="stat-label">Total API Cost</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="totalTokens">0</div>
            <div class="stat-label">Total Tokens</div>
        </div>
        <div class="stat">
            <div class="auto-refresh-indicator">
                <div class="refresh-dot" id="refreshDot"></div>
                <span id="lastUpdate">Never updated</span>
            </div>
        </div>
    </div>

    <div class="sessions-grid" id="sessionsGrid">
        <div class="empty-state">
            <div class="empty-state-icon">Loading...</div>
            <p>Loading sessions...</p>
        </div>
    </div>

    <script>
        let autoRefresh = true;
        let refreshInterval = null;

        function formatDate(isoString) {
            if (!isoString) return 'Unknown';
            const date = new Date(isoString);
            return date.toLocaleString();
        }

        function formatCost(cost) {
            if (cost === undefined || cost === null) return '$0.00';
            return '$' + cost.toFixed(2);
        }

        function formatTokens(tokens) {
            if (!tokens) return '0';
            return tokens.toLocaleString();
        }

        function getStatusIcon(status) {
            switch(status) {
                case 'completed': return 'x';
                case 'in_progress': return '>';
                default: return '';
            }
        }

        async function copyToClipboard(text, element) {
            try {
                await navigator.clipboard.writeText(text);
                // Show brief visual feedback
                const originalBg = element.style.background;
                element.style.background = '#00ff88';
                element.style.color = '#000';
                setTimeout(() => {
                    element.style.background = '';
                    element.style.color = '';
                }, 200);
            } catch (err) {
                console.error('Failed to copy:', err);
            }
        }

        async function fetchSessions() {
            try {
                const response = await fetch('/api/sessions');
                return await response.json();
            } catch (error) {
                console.error('Error fetching sessions:', error);
                return { sessions: [], costs: {}, total_cost: 0 };
            }
        }

        async function clearSession(sessionId) {
            if (!confirm(`Clear session ${sessionId.substring(0, 8)}...?`)) return;

            try {
                const response = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
                if (response.ok) {
                    refreshData();
                } else {
                    alert('Failed to clear session');
                }
            } catch (error) {
                console.error('Error clearing session:', error);
                alert('Error clearing session');
            }
        }

        async function clearAllSessions() {
            if (!confirm('Clear ALL sessions? This cannot be undone.')) return;

            try {
                const response = await fetch('/api/sessions', { method: 'DELETE' });
                if (response.ok) {
                    refreshData();
                } else {
                    alert('Failed to clear sessions');
                }
            } catch (error) {
                console.error('Error clearing sessions:', error);
                alert('Error clearing sessions');
            }
        }

        function renderSessions(data) {
            const grid = document.getElementById('sessionsGrid');
            const sessions = data.sessions || [];

            // Calculate totals from plan sessions (accumulated_cost)
            let totalCost = 0;
            let totalInputTokens = 0;
            let totalOutputTokens = 0;
            let totalCompleted = 0;

            sessions.forEach(s => {
                totalCost += s.accumulated_cost || 0;
                totalInputTokens += s.total_input_tokens || 0;
                totalOutputTokens += s.total_output_tokens || 0;
                totalCompleted += (s.items || []).filter(i => i.status === 'completed').length;
            });

            // Update stats
            document.getElementById('totalSessions').textContent = sessions.length;
            document.getElementById('totalCost').textContent = formatCost(totalCost);
            document.getElementById('totalTokens').textContent = formatTokens(totalInputTokens + totalOutputTokens);
            document.getElementById('completedTasks').textContent = totalCompleted;

            // Update last update time
            document.getElementById('lastUpdate').textContent = 'Updated ' + new Date().toLocaleTimeString();

            if (sessions.length === 0) {
                grid.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">(empty)</div>
                        <p>No active plan sessions found</p>
                    </div>
                `;
                return;
            }

            // Sort sessions by updated_at or created_at descending (newest first)
            sessions.sort((a, b) => {
                const aTime = new Date(a.updated_at || a.created_at);
                const bTime = new Date(b.updated_at || b.created_at);
                return bTime - aTime;
            });

            // Render plan session cards only (no separate cost sessions)
            const planCardsHtml = sessions.map(session => {
                const items = session.items || [];
                const completed = items.filter(i => i.status === 'completed').length;
                const inProgress = items.filter(i => i.status === 'in_progress').length;
                const total = items.length;
                const percent = total > 0 ? Math.round((completed / total) * 100) : 0;
                const isComplete = total > 0 && completed === total;

                // Use accumulated cost from plan state (linked cost)
                const cost = session.accumulated_cost || 0;
                const inputTokens = session.total_input_tokens || 0;
                const outputTokens = session.total_output_tokens || 0;
                const toolCalls = session.tool_calls || 0;

                const itemsHtml = items.map(item => `
                    <div class="item">
                        <div class="item-status ${item.status}">${getStatusIcon(item.status)}</div>
                        <div class="item-text ${item.status}">${item.task}</div>
                    </div>
                `).join('');

                return `
                    <div class="session-card">
                        <div class="session-header">
                            <div class="session-name">${session.name || 'Unnamed Session'}</div>
                            <div class="session-id"
                                 title="${session.session_id}"
                                 onclick="copyToClipboard('${session.session_id}', this)">
                                ${session.session_id.substring(0, 8)}...
                            </div>
                        </div>

                        <div class="progress-section">
                            <div class="progress-bar-container">
                                <div class="progress-bar ${isComplete ? 'complete' : ''}" style="width: ${percent}%"></div>
                            </div>
                            <div class="progress-text">
                                <span class="progress-count">${completed}/${total} tasks</span>
                                <span class="progress-percent">${percent}%${inProgress > 0 ? ' (' + inProgress + ' in progress)' : ''}</span>
                            </div>
                        </div>

                        <div class="cost-section">
                            <div>
                                <div class="cost-amount">${cost > 0 ? formatCost(cost) : '$0.00'}</div>
                                <div class="cost-label">Plan Cost</div>
                            </div>
                            <div class="tokens-info">
                                ${inputTokens > 0 || outputTokens > 0
                                    ? formatTokens(inputTokens) + ' in / ' + formatTokens(outputTokens) + ' out'
                                    : 'No API calls yet'}
                            </div>
                        </div>

                        ${toolCalls > 0 ? `<div style="color: #888; font-size: 0.8rem; margin-bottom: 12px;">Tool calls: ${toolCalls}</div>` : ''}

                        ${items.length > 0 ? `
                            <div class="items-list">
                                ${itemsHtml}
                            </div>
                        ` : '<div style="color: #666; font-size: 0.85rem; margin-bottom: 16px;">No plan items</div>'}

                        <div class="session-footer">
                            <div class="session-time">
                                Created: ${formatDate(session.created_at)}<br>
                                Updated: ${formatDate(session.updated_at)}
                            </div>
                            <button class="btn btn-danger btn-clear" onclick="clearSession('${session.session_id}')">
                                Clear
                            </button>
                        </div>
                    </div>
                `;
            }).join('');

            grid.innerHTML = planCardsHtml;
        }

        async function refreshData() {
            const data = await fetchSessions();
            renderSessions(data);
        }

        function toggleAutoRefresh() {
            autoRefresh = !autoRefresh;
            const btn = document.getElementById('autoRefreshBtn');
            const dot = document.getElementById('refreshDot');

            btn.textContent = `Auto-refresh: ${autoRefresh ? 'ON' : 'OFF'}`;
            dot.classList.toggle('paused', !autoRefresh);

            if (autoRefresh) {
                startAutoRefresh();
            } else {
                stopAutoRefresh();
            }
        }

        function startAutoRefresh() {
            if (refreshInterval) clearInterval(refreshInterval);
            refreshInterval = setInterval(refreshData, 5000);
        }

        function stopAutoRefresh() {
            if (refreshInterval) {
                clearInterval(refreshInterval);
                refreshInterval = null;
            }
        }

        // Initial load
        refreshData();
        startAutoRefresh();
    </script>
</body>
</html>
"""


def load_sessions():
    """Load all session plan state files."""
    sessions = []

    if not SESSIONS_DIR.exists():
        return sessions

    for session_file in SESSIONS_DIR.glob("*_plan_state.json"):
        try:
            with open(session_file, "r") as f:
                session_data = json.load(f)
                sessions.append(session_data)
        except Exception as e:
            print(f"Error loading {session_file}: {e}")

    return sessions




def clear_session(session_id: str) -> bool:
    """Clear a specific session's plan state file."""
    session_file = SESSIONS_DIR / f"{session_id}_plan_state.json"

    if session_file.exists():
        try:
            session_file.unlink()
            return True
        except Exception as e:
            print(f"Error deleting {session_file}: {e}")

    return False


def clear_all_sessions() -> bool:
    """Clear all session plan state files."""
    if not SESSIONS_DIR.exists():
        return True

    success = True
    for session_file in SESSIONS_DIR.glob("*_plan_state.json"):
        try:
            session_file.unlink()
        except Exception as e:
            print(f"Error deleting {session_file}: {e}")
            success = False

    return success


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def send_json(self, data: dict, status: int = 200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_html(self, html: str):
        """Send HTML response."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_html(HTML_TEMPLATE)

        elif path == "/api/sessions":
            sessions = load_sessions()

            # Calculate total cost from plan sessions
            total_cost = sum(s.get("accumulated_cost", 0) for s in sessions)

            self.send_json({
                "sessions": sessions,
                "total_cost": total_cost
            })

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        """Handle DELETE requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/sessions":
            # Clear all sessions
            success = clear_all_sessions()
            self.send_json({"success": success})

        elif path.startswith("/api/sessions/"):
            # Clear specific session
            session_id = path.split("/")[-1]
            success = clear_session(session_id)
            self.send_json({"success": success})

        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    """Start the dashboard server."""
    server = HTTPServer(("localhost", PORT), DashboardHandler)

    print(f"""
============================================================
           Claude Session Progress Dashboard
============================================================
  Server running at: http://localhost:{PORT}
  Press Ctrl+C to stop
============================================================
""")

    try:
        import webbrowser
        webbrowser.open(f"http://localhost:{PORT}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
