import { useState, Fragment } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, LayoutGrid, ShieldCheck } from 'lucide-react';
import FilePreviewModal from './FilePreviewModal';

const refPatterns = [
  { regex: /file #(\d+)/gi, type: 'file', icon: FileText, color: '#22c55e', route: '/files' },
  { regex: /Mission #(\d+)/gi, type: 'mission', icon: LayoutGrid, color: '#38bdf8', route: '/missions' },
  { regex: /Action #(\d+)/gi, type: 'action', icon: ShieldCheck, color: '#f59e0b', route: '/actions' },
];

export default function SmartMessage({ content }) {
  const navigate = useNavigate();
  const [previewFileId, setPreviewFileId] = useState(null);

  if (!content) return null;

  // Parse the content into segments: plain text + reference chips
  const segments = [];
  let remaining = content;

  // Build a combined regex to find all references
  const combined = /(?:file|Mission|Action) #(\d+)/gi;
  let lastIndex = 0;
  const matches = [...content.matchAll(combined)];

  if (matches.length === 0) {
    // No references — just render with bold support
    return (
      <>
        <BoldText text={content} />
        {previewFileId && <FilePreviewModal fileId={previewFileId} onClose={() => setPreviewFileId(null)} />}
      </>
    );
  }

  for (const match of matches) {
    // Add text before this match
    if (match.index > lastIndex) {
      segments.push({ type: 'text', value: content.slice(lastIndex, match.index) });
    }

    const fullMatch = match[0];
    const id = parseInt(match[1]);
    const lower = fullMatch.toLowerCase();

    if (lower.startsWith('file')) {
      segments.push({ type: 'file', id, label: fullMatch });
    } else if (lower.startsWith('mission')) {
      segments.push({ type: 'mission', id, label: fullMatch });
    } else if (lower.startsWith('action')) {
      segments.push({ type: 'action', id, label: fullMatch });
    }

    lastIndex = match.index + fullMatch.length;
  }

  // Add remaining text
  if (lastIndex < content.length) {
    segments.push({ type: 'text', value: content.slice(lastIndex) });
  }

  const chipConfig = {
    file: { icon: FileText, color: '#22c55e' },
    mission: { icon: LayoutGrid, color: '#38bdf8' },
    action: { icon: ShieldCheck, color: '#f59e0b' },
  };

  function handleChipClick(type, id) {
    if (type === 'file') {
      setPreviewFileId(id);
    } else if (type === 'mission') {
      navigate('/missions');
    } else if (type === 'action') {
      navigate('/actions');
    }
  }

  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === 'text') {
          return <BoldText key={i} text={seg.value} />;
        }
        const cfg = chipConfig[seg.type];
        const Icon = cfg.icon;
        return (
          <button
            key={i}
            onClick={e => { e.stopPropagation(); handleChipClick(seg.type, seg.id); }}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 mx-0.5 rounded border text-[11px] hover:brightness-125 transition-all mono-heading align-baseline"
            style={{
              color: cfg.color,
              backgroundColor: `${cfg.color}15`,
              borderColor: `${cfg.color}30`,
            }}
          >
            <Icon size={10} />
            {seg.label}
          </button>
        );
      })}
      {previewFileId && <FilePreviewModal fileId={previewFileId} onClose={() => setPreviewFileId(null)} />}
    </>
  );
}

function BoldText({ text }) {
  // Support **bold** syntax
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return <strong key={i} className="font-semibold text-[var(--text-primary)]">{part.slice(2, -2)}</strong>;
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}
