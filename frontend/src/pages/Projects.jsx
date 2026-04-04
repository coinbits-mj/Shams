import { useState, useEffect } from 'react';
import { get } from '../api';
import { ChevronDown, ChevronRight, Circle, CheckCircle, Clock, AlertTriangle, Lock } from 'lucide-react';

const agentColors = {
  shams: '#f59e0b', rumi: '#06b6d4', leo: '#22c55e',
  wakil: '#a855f7', scout: '#ef4444', builder: '#3b82f6',
};
const statusIcons = {
  inbox: Circle, assigned: Clock, active: Clock, review: AlertTriangle, done: CheckCircle, dropped: Circle,
};
const priorityColors = { urgent: '#ef4444', high: '#f97316', normal: '#38bdf8', low: '#64748b' };

export default function Projects() {
  const [projects, setProjects] = useState([]);
  const [expandedBrief, setExpandedBrief] = useState(null);

  useEffect(() => { get('/gantt').then(d => d && setProjects(d)); }, []);

  // Calculate timeline bounds
  let minDate = new Date();
  let maxDate = new Date();
  minDate.setDate(minDate.getDate() - 7);
  maxDate.setMonth(maxDate.getMonth() + 3);

  projects.forEach(p => {
    if (p.start_date) { const d = new Date(p.start_date); if (d < minDate) minDate = d; }
    if (p.target_date) { const d = new Date(p.target_date); if (d > maxDate) maxDate = d; }
    p.tasks?.forEach(t => {
      if (t.start_date) { const d = new Date(t.start_date); if (d < minDate) minDate = d; }
      if (t.end_date) { const d = new Date(t.end_date); if (d > maxDate) maxDate = d; }
    });
  });

  const totalDays = Math.max(Math.ceil((maxDate - minDate) / (1000 * 60 * 60 * 24)), 30);
  const today = new Date();
  const todayOffset = Math.ceil((today - minDate) / (1000 * 60 * 60 * 24));

  function getBarStyle(startStr, endStr, color) {
    if (!startStr) return null;
    const start = new Date(startStr);
    const end = endStr ? new Date(endStr) : new Date(start.getTime() + 7 * 24 * 60 * 60 * 1000);
    const left = Math.max(0, (start - minDate) / (1000 * 60 * 60 * 24));
    const width = Math.max(1, (end - start) / (1000 * 60 * 60 * 24));
    return {
      left: `${(left / totalDays) * 100}%`,
      width: `${(width / totalDays) * 100}%`,
      backgroundColor: `${color}30`,
      borderLeft: `3px solid ${color}`,
    };
  }

  // Generate month markers
  const months = [];
  const cursor = new Date(minDate);
  cursor.setDate(1);
  while (cursor <= maxDate) {
    const offset = (cursor - minDate) / (1000 * 60 * 60 * 24);
    if (offset >= 0) {
      months.push({
        label: cursor.toLocaleDateString('en-US', { month: 'short', year: '2-digit' }),
        left: `${(offset / totalDays) * 100}%`,
      });
    }
    cursor.setMonth(cursor.getMonth() + 1);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6">
        <h1 className="mono-heading text-2xl text-[var(--text-primary)] mb-6">projects</h1>

        {projects.length === 0 && (
          <p className="text-sm text-[var(--text-muted)] text-center py-12">no active projects</p>
        )}

        {projects.map(project => {
          const isExpanded = expandedBrief === project.id;
          return (
            <div key={project.id} className="mb-8">
              {/* Project Header + Brief */}
              <div className="glass-card p-4 mb-3">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3 cursor-pointer" onClick={() => setExpandedBrief(isExpanded ? null : project.id)}>
                    <div className="w-3 h-3 rounded-full" style={{ backgroundColor: project.color }} />
                    <div>
                      <h2 className="mono-heading text-lg text-[var(--text-primary)]">{project.title}</h2>
                      <div className="flex items-center gap-3 mt-1">
                        {project.start_date && <span className="text-[10px] text-[var(--text-muted)]">{project.start_date}</span>}
                        {project.target_date && <span className="text-[10px] text-[var(--text-muted)]">→ {project.target_date}</span>}
                        <span className="text-[10px] text-[var(--text-muted)]">{project.tasks?.length || 0} tasks</span>
                        {isExpanded ? <ChevronDown size={12} className="text-[var(--text-muted)]" /> : <ChevronRight size={12} className="text-[var(--text-muted)]" />}
                      </div>
                    </div>
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded mono-heading" style={{ color: project.color, backgroundColor: `${project.color}15` }}>{project.status}</span>
                </div>

                {/* Brief (expandable) */}
                {isExpanded && project.brief && (
                  <div className="mt-3 p-3 rounded-lg bg-[var(--bg-deep)] border border-[var(--border)] text-sm text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">
                    {project.brief}
                  </div>
                )}
              </div>

              {/* Gantt Chart */}
              <div className="glass-card overflow-hidden">
                {/* Timeline header */}
                <div className="relative h-6 border-b border-[var(--border)] bg-[var(--bg-deep)]">
                  {months.map((m, i) => (
                    <div key={i} className="absolute top-0 h-full border-l border-[var(--border)] flex items-center" style={{ left: m.left }}>
                      <span className="text-[9px] text-[var(--text-muted)] mono-heading px-1">{m.label}</span>
                    </div>
                  ))}
                  {/* Today marker */}
                  <div className="absolute top-0 h-full w-px bg-[var(--red)]" style={{ left: `${(todayOffset / totalDays) * 100}%` }}>
                    <span className="absolute -top-0 left-1 text-[8px] text-[var(--red)] mono-heading">today</span>
                  </div>
                </div>

                {/* Task rows */}
                {project.tasks?.map(task => {
                  const StatusIcon = statusIcons[task.status] || Circle;
                  const barStyle = getBarStyle(task.start_date, task.end_date, project.color);
                  const isDone = task.status === 'done' || task.status === 'dropped';
                  const hasDeps = task.depends_on?.length > 0;

                  return (
                    <div key={task.id} className={`flex border-b border-[var(--border)] last:border-b-0 ${isDone ? 'opacity-50' : ''}`}>
                      {/* Left label */}
                      <div className="w-72 flex-shrink-0 p-2.5 border-r border-[var(--border)] flex items-center gap-2">
                        <StatusIcon size={12} style={{ color: isDone ? '#22c55e' : priorityColors[task.priority] || '#64748b' }} />
                        <div className="flex-1 min-w-0">
                          <p className={`text-xs truncate ${isDone ? 'line-through text-[var(--text-muted)]' : 'text-[var(--text-primary)]'}`}>{task.title}</p>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            {task.assigned_agent && (
                              <span className="text-[9px] mono-heading" style={{ color: agentColors[task.assigned_agent] }}>{task.assigned_agent}</span>
                            )}
                            {hasDeps && <Lock size={8} className="text-[var(--text-muted)]" />}
                            <span className="text-[9px] text-[var(--text-muted)]">{task.status}</span>
                          </div>
                        </div>
                      </div>

                      {/* Right timeline */}
                      <div className="flex-1 relative h-12">
                        {/* Grid lines */}
                        {months.map((m, i) => (
                          <div key={i} className="absolute top-0 h-full border-l border-[var(--border)] opacity-30" style={{ left: m.left }} />
                        ))}
                        {/* Today */}
                        <div className="absolute top-0 h-full w-px bg-[var(--red)] opacity-40" style={{ left: `${(todayOffset / totalDays) * 100}%` }} />
                        {/* Bar */}
                        {barStyle && (
                          <div className="absolute top-2.5 h-7 rounded-r-md flex items-center px-2" style={barStyle}>
                            {task.start_date && (
                              <span className="text-[8px] text-[var(--text-muted)] mono-heading whitespace-nowrap">
                                {new Date(task.start_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                                {task.end_date && ` → ${new Date(task.end_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`}
                              </span>
                            )}
                          </div>
                        )}
                        {/* Dependency arrows */}
                        {hasDeps && task.depends_on.map(depId => {
                          const depTask = project.tasks.find(t => t.id === depId);
                          if (!depTask?.end_date) return null;
                          const depEnd = new Date(depTask.end_date);
                          const depOffset = (depEnd - minDate) / (1000 * 60 * 60 * 24);
                          return (
                            <div key={depId} className="absolute top-5 w-2 h-2 rounded-full bg-[var(--text-muted)]"
                              style={{ left: `${(depOffset / totalDays) * 100}%` }} />
                          );
                        })}
                      </div>
                    </div>
                  );
                })}

                {(!project.tasks || project.tasks.length === 0) && (
                  <div className="p-4 text-xs text-[var(--text-muted)] text-center">no tasks yet</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
