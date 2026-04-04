import { useState, useEffect, useRef } from 'react';
import { get, patch, post, upload } from '../api';
import { ChevronDown, ChevronRight, Circle, CheckCircle, Clock, AlertTriangle, Lock, X, FileText, Paperclip, Image, LayoutGrid, GanttChart } from 'lucide-react';
import SmartMessage from '../components/SmartMessage';
import FilePreviewModal from '../components/FilePreviewModal';
import ChatInput from '../components/ChatInput';

const agentColors = {
  shams: '#f59e0b', rumi: '#06b6d4', leo: '#22c55e',
  wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6',
};
const priorityColors = { urgent: '#ef4444', high: '#f97316', normal: '#38bdf8', low: '#64748b' };
const kanbanColumns = ['inbox', 'assigned', 'active', 'review', 'done'];
const kanbanLabels = { inbox: 'Inbox', assigned: 'Assigned', active: 'Active', review: 'Review', done: 'Done' };

export default function Projects() {
  const [projects, setProjects] = useState([]);
  const [activeProject, setActiveProject] = useState(null);
  const [viewMode, setViewMode] = useState('board'); // 'board' or 'timeline'
  const [selectedTask, setSelectedTask] = useState(null);
  const [taskDetail, setTaskDetail] = useState(null);
  const [previewFileId, setPreviewFileId] = useState(null);

  // Chat state for task-level conversation
  const [chatMessages, setChatMessages] = useState([]);
  const [chatLoading, setChatLoading] = useState(false);
  const chatBottomRef = useRef(null);

  async function loadProjects() {
    const d = await get('/gantt');
    if (d) {
      setProjects(d);
      // Refresh active project if one is selected
      if (activeProject) {
        const updated = d.find(p => p.id === activeProject.id);
        if (updated) setActiveProject(updated);
      }
    }
  }

  useEffect(() => { loadProjects(); }, []);

  // Load task detail when selected
  useEffect(() => {
    if (!selectedTask) { setTaskDetail(null); return; }
    get(`/missions/${selectedTask.id}`).then(d => {
      if (d) setTaskDetail(d);
    });
  }, [selectedTask?.id]);

  // Auto-scroll chat
  useEffect(() => { chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatMessages]);

  async function moveMission(missionId, newStatus) {
    await patch(`/missions/${missionId}`, { status: newStatus });
    loadProjects();
    if (taskDetail?.id === missionId) {
      const d = await get(`/missions/${missionId}`);
      if (d) setTaskDetail(d);
    }
  }

  async function handleTaskChat(message, files) {
    if (!message && files.length === 0) return;
    const taskContext = taskDetail ? `[Context: working on "${taskDetail.title}" for project "${activeProject?.title}"]` : '';
    const fullMessage = `${taskContext}\n\n${message}`;
    setChatMessages(prev => [...prev, { role: 'user', content: message }]);
    setChatLoading(true);
    let data;
    if (files.length > 0) {
      data = await upload('/chat', fullMessage, files);
    } else {
      data = await post('/chat', { message: fullMessage });
    }
    if (data?.reply) setChatMessages(prev => [...prev, { role: 'assistant', content: data.reply }]);
    setChatLoading(false);
  }

  // ─── PANE 1: Project List ────────────────────────────────────────
  function renderProjectList() {
    return (
      <div className="w-56 flex-shrink-0 border-r border-[var(--border)] bg-[var(--bg-surface)] flex flex-col h-full">
        <div className="p-3 border-b border-[var(--border)]">
          <span className="mono-heading text-sm text-[var(--text-primary)]">projects</span>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {projects.map(p => (
            <button key={p.id} onClick={() => { setActiveProject(p); setSelectedTask(null); setChatMessages([]); }}
              className={`w-full text-left p-2.5 rounded-lg transition-colors ${
                activeProject?.id === p.id
                  ? 'bg-[var(--accent-glow)] border border-[var(--border-bright)]'
                  : 'hover:bg-[var(--bg-hover)]'
              }`}>
              <div className="flex items-center gap-2 mb-0.5">
                <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: p.color }} />
                <span className="text-xs text-[var(--text-primary)] truncate">{p.title}</span>
              </div>
              <div className="flex items-center gap-2 ml-4">
                <span className="text-[9px] text-[var(--text-muted)]">{p.tasks?.length || 0} tasks</span>
                {p.target_date && <span className="text-[9px] text-[var(--text-muted)]">→ {p.target_date}</span>}
              </div>
            </button>
          ))}
          {projects.length === 0 && (
            <p className="text-[10px] text-[var(--text-muted)] text-center py-4">no projects</p>
          )}
        </div>
      </div>
    );
  }

  // ─── PANE 2: Middle Pane (Board or Timeline) ─────────────────────
  function renderMiddle() {
    if (!activeProject) {
      return (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-sm text-[var(--text-muted)]">select a project</p>
        </div>
      );
    }

    const tasks = activeProject.tasks || [];
    const tasksByStatus = {};
    kanbanColumns.forEach(c => { tasksByStatus[c] = tasks.filter(t => t.status === c); });

    // Timeline calculations
    let minDate = new Date();
    let maxDate = new Date();
    minDate.setDate(minDate.getDate() - 7);
    maxDate.setMonth(maxDate.getMonth() + 3);
    if (activeProject.start_date) { const d = new Date(activeProject.start_date); if (d < minDate) minDate = d; }
    if (activeProject.target_date) { const d = new Date(activeProject.target_date); if (d > maxDate) maxDate = d; }
    tasks.forEach(t => {
      if (t.start_date) { const d = new Date(t.start_date); if (d < minDate) minDate = d; }
      if (t.end_date) { const d = new Date(t.end_date); if (d > maxDate) maxDate = d; }
    });
    const totalDays = Math.max(Math.ceil((maxDate - minDate) / (1000 * 60 * 60 * 24)), 30);
    const today = new Date();
    const todayOffset = Math.ceil((today - minDate) / (1000 * 60 * 60 * 24));
    const months = [];
    const cursor = new Date(minDate);
    cursor.setDate(1);
    while (cursor <= maxDate) {
      const offset = (cursor - minDate) / (1000 * 60 * 60 * 24);
      if (offset >= 0) months.push({ label: cursor.toLocaleDateString('en-US', { month: 'short' }), left: `${(offset / totalDays) * 100}%` });
      cursor.setMonth(cursor.getMonth() + 1);
    }

    function getBarStyle(startStr, endStr) {
      if (!startStr) return null;
      const start = new Date(startStr);
      const end = endStr ? new Date(endStr) : new Date(start.getTime() + 7 * 86400000);
      const left = Math.max(0, (start - minDate) / 86400000);
      const width = Math.max(1, (end - start) / 86400000);
      return { left: `${(left / totalDays) * 100}%`, width: `${(width / totalDays) * 100}%`, backgroundColor: `${activeProject.color}30`, borderLeft: `3px solid ${activeProject.color}` };
    }

    return (
      <div className="flex-1 flex flex-col min-w-0">
        {/* Project header with view toggle */}
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: activeProject.color }} />
              <h2 className="mono-heading text-sm text-[var(--text-primary)]">{activeProject.title}</h2>
              <span className="text-[10px] text-[var(--text-muted)]">
                {activeProject.start_date} → {activeProject.target_date || '?'}
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-muted)] mono-heading">
              {tasks.filter(t => t.status === 'done').length} of {tasks.length} done
            </span>
          </div>
          {activeProject.brief && (
            <p className="text-[11px] text-[var(--text-muted)] mt-1 ml-4 line-clamp-2">{activeProject.brief}</p>
          )}
        </div>

        {/* Board view — top half */}
        <div className="flex-1 overflow-x-auto p-3 min-h-0">
          <div className="flex gap-2 h-full min-w-max">
            {kanbanColumns.map(col => (
              <div key={col} className="w-52 flex flex-col">
                <div className="flex items-center justify-between px-1.5 py-1.5 mb-1.5">
                  <span className="mono-heading text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{kanbanLabels[col]}</span>
                  <span className="text-[9px] px-1 py-0.5 rounded bg-[var(--bg-card)] text-[var(--text-muted)]">
                    {tasksByStatus[col]?.length || 0}
                  </span>
                </div>
                <div className="flex-1 space-y-1.5 overflow-y-auto">
                  {(tasksByStatus[col] || []).map(task => {
                    const isSelected = selectedTask?.id === task.id;
                    return (
                      <div key={task.id}
                        className={`p-2.5 rounded-lg border cursor-pointer group transition-colors ${
                          isSelected
                            ? 'bg-[var(--accent-glow)] border-[var(--border-bright)]'
                            : 'bg-[var(--bg-card)] border-[var(--border)] hover:border-[var(--border-bright)]'
                        }`}
                        onClick={() => { setSelectedTask(task); setChatMessages([]); }}>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[9px] px-1 py-0.5 rounded uppercase tracking-wider mono-heading"
                            style={{ color: priorityColors[task.priority], backgroundColor: `${priorityColors[task.priority]}10` }}>
                            {task.priority}
                          </span>
                          {task.assigned_agent && (
                            <span className="text-[9px] mono-heading" style={{ color: agentColors[task.assigned_agent] }}>{task.assigned_agent}</span>
                          )}
                        </div>
                        <p className="text-xs text-[var(--text-primary)] leading-tight">{task.title}</p>
                        {task.depends_on?.length > 0 && (
                          <div className="flex items-center gap-1 mt-1">
                            <Lock size={8} className="text-[var(--text-muted)]" />
                            <span className="text-[8px] text-[var(--text-muted)]">blocked</span>
                          </div>
                        )}
                        {col !== 'done' && (
                          <div className="mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button onClick={e => { e.stopPropagation(); moveMission(task.id, kanbanColumns[kanbanColumns.indexOf(col) + 1]); }}
                              className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)] mono-heading">
                              {kanbanLabels[kanbanColumns[kanbanColumns.indexOf(col) + 1]]} →
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Timeline view — bottom half */}
        <div className="h-64 flex-shrink-0 border-t border-[var(--border)] overflow-auto">
            {/* Month headers */}
            <div className="relative h-6 border-b border-[var(--border)] bg-[var(--bg-deep)] sticky top-0 z-10">
              {months.map((m, i) => (
                <div key={i} className="absolute top-0 h-full border-l border-[var(--border)] flex items-center" style={{ left: m.left }}>
                  <span className="text-[9px] text-[var(--text-muted)] mono-heading px-1">{m.label}</span>
                </div>
              ))}
              <div className="absolute top-0 h-full w-px bg-[var(--red)]" style={{ left: `${(todayOffset / totalDays) * 100}%` }}>
                <span className="absolute -top-0 left-1 text-[8px] text-[var(--red)] mono-heading">today</span>
              </div>
            </div>

            {/* Task rows */}
            {tasks.map(task => {
              const isDone = task.status === 'done' || task.status === 'dropped';
              const isSelected = selectedTask?.id === task.id;
              const barStyle = getBarStyle(task.start_date, task.end_date);

              return (
                <div key={task.id}
                  className={`flex border-b border-[var(--border)] last:border-b-0 cursor-pointer ${isDone ? 'opacity-40' : ''} ${isSelected ? 'bg-[var(--accent-glow)]' : 'hover:bg-[var(--bg-hover)]'}`}
                  onClick={() => { setSelectedTask(task); setChatMessages([]); }}>
                  {/* Label */}
                  <div className="w-56 flex-shrink-0 p-2 border-r border-[var(--border)] flex items-center gap-2">
                    <CheckCircle size={10} style={{ color: isDone ? '#22c55e' : priorityColors[task.priority] || '#64748b' }} />
                    <div className="flex-1 min-w-0">
                      <p className={`text-[11px] truncate ${isDone ? 'line-through text-[var(--text-muted)]' : 'text-[var(--text-primary)]'}`}>{task.title}</p>
                      <div className="flex items-center gap-1 mt-0.5">
                        {task.assigned_agent && <span className="text-[8px] mono-heading" style={{ color: agentColors[task.assigned_agent] }}>{task.assigned_agent}</span>}
                        {task.depends_on?.length > 0 && <Lock size={7} className="text-[var(--text-muted)]" />}
                        <span className="text-[8px] text-[var(--text-muted)]">{task.status}</span>
                      </div>
                    </div>
                  </div>
                  {/* Bar */}
                  <div className="flex-1 relative h-10">
                    {months.map((m, i) => (
                      <div key={i} className="absolute top-0 h-full border-l border-[var(--border)] opacity-20" style={{ left: m.left }} />
                    ))}
                    <div className="absolute top-0 h-full w-px bg-[var(--red)] opacity-30" style={{ left: `${(todayOffset / totalDays) * 100}%` }} />
                    {barStyle && (
                      <div className="absolute top-2 h-6 rounded-r-md flex items-center px-2" style={barStyle}>
                        <span className="text-[8px] text-[var(--text-muted)] mono-heading whitespace-nowrap">
                          {task.start_date && new Date(task.start_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                          {task.end_date && ` → ${new Date(task.end_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    );
  }

  // ─── PANE 3: Task Detail + Work Product ──────────────────────────
  function renderDetail() {
    if (!selectedTask) {
      return (
        <div className="w-80 flex-shrink-0 border-l border-[var(--border)] bg-[var(--bg-surface)] flex items-center justify-center">
          <p className="text-xs text-[var(--text-muted)]">select a task</p>
        </div>
      );
    }

    const detail = taskDetail || selectedTask;

    return (
      <div className="w-96 flex-shrink-0 border-l border-[var(--border)] bg-[var(--bg-surface)] flex flex-col h-full">
        {/* Task header */}
        <div className="p-4 border-b border-[var(--border)]">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] px-1.5 py-0.5 rounded mono-heading uppercase"
                style={{ color: priorityColors[detail.priority], backgroundColor: `${priorityColors[detail.priority]}15` }}>
                {detail.priority}
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-hover)] text-[var(--text-muted)] mono-heading">{detail.status}</span>
            </div>
            <button onClick={() => setSelectedTask(null)} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
              <X size={14} />
            </button>
          </div>
          <h3 className="text-sm text-[var(--text-primary)] leading-tight">{detail.title}</h3>
          {detail.assigned_agent && (
            <span className="text-[10px] mono-heading mt-1 inline-block" style={{ color: agentColors[detail.assigned_agent] }}>@{detail.assigned_agent}</span>
          )}
          {detail.description && (
            <p className="text-xs text-[var(--text-secondary)] mt-2 leading-relaxed">{detail.description}</p>
          )}
          {(detail.start_date || detail.end_date) && (
            <p className="text-[10px] text-[var(--text-muted)] mt-2">{detail.start_date || '?'} → {detail.end_date || '?'}</p>
          )}
        </div>

        {/* Linked files */}
        {taskDetail?.files?.length > 0 && (
          <div className="px-4 py-2 border-b border-[var(--border)]">
            <span className="text-[10px] text-[var(--text-muted)] mono-heading">files</span>
            <div className="mt-1 space-y-1">
              {taskDetail.files.map(f => (
                <button key={f.id} onClick={() => setPreviewFileId(f.id)}
                  className="w-full flex items-center gap-2 p-1.5 rounded bg-[var(--bg-card)] border border-[var(--border)] hover:border-[var(--border-bright)] text-left">
                  <FileText size={10} className="text-[#22c55e] flex-shrink-0" />
                  <span className="text-[11px] text-[var(--text-primary)] truncate">{f.filename}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Linked actions */}
        {taskDetail?.actions?.length > 0 && (
          <div className="px-4 py-2 border-b border-[var(--border)]">
            <span className="text-[10px] text-[var(--text-muted)] mono-heading">actions</span>
            <div className="mt-1 space-y-1">
              {taskDetail.actions.map(a => (
                <div key={a.id} className="flex items-center justify-between p-1.5 rounded bg-[var(--bg-card)] border border-[var(--border)]">
                  <span className="text-[11px] text-[var(--text-primary)] truncate">{a.title}</span>
                  <span className={`text-[9px] px-1 rounded ${
                    a.status === 'completed' ? 'text-[#22c55e]' : a.status === 'pending' ? 'text-[#f59e0b]' : 'text-[var(--text-muted)]'
                  }`}>{a.status}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Timeline */}
        {taskDetail?.activity?.length > 0 && (
          <div className="px-4 py-2 border-b border-[var(--border)] max-h-32 overflow-y-auto">
            <span className="text-[10px] text-[var(--text-muted)] mono-heading">timeline</span>
            <div className="mt-1 space-y-0.5 border-l border-[var(--border)] ml-1 pl-2">
              {taskDetail.activity.slice(0, 8).map((a, i) => (
                <div key={i} className="py-0.5">
                  <span className="text-[9px] text-[var(--text-muted)]">
                    {a.timestamp ? new Date(a.timestamp).toLocaleDateString([], { month: 'short', day: 'numeric' }) : ''}
                  </span>
                  <p className="text-[10px] text-[var(--text-secondary)]">{a.content}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Chat with Shams about this task */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="px-4 py-2 border-b border-[var(--border)]">
            <span className="text-[10px] text-[var(--text-muted)] mono-heading">work on this task with shams</span>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {chatMessages.length === 0 && (
              <p className="text-[10px] text-[var(--text-muted)] text-center py-4">
                ask shams to work on this — draft a doc, research, update status...
              </p>
            )}
            {chatMessages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[90%] rounded-lg px-2.5 py-1.5 text-[11px] whitespace-pre-wrap ${
                  m.role === 'user'
                    ? 'bg-[var(--accent-glow)] text-[var(--accent)] border border-[var(--border-bright)]'
                    : 'bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-primary)]'
                }`}>
                  <SmartMessage content={m.content} />
                </div>
              </div>
            ))}
            {chatLoading && (
              <div className="flex justify-start">
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-[11px] text-[var(--text-muted)]">
                  <span className="pulse-active">working...</span>
                </div>
              </div>
            )}
            <div ref={chatBottomRef} />
          </div>
          <ChatInput
            onSend={handleTaskChat}
            placeholder="work on this task..."
            disabled={chatLoading}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {renderProjectList()}
      {renderMiddle()}
      {renderDetail()}
      {previewFileId && <FilePreviewModal fileId={previewFileId} onClose={() => setPreviewFileId(null)} />}
    </div>
  );
}
