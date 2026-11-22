import { useEffect, useId, useRef, type ReactNode } from "react";

const glyphs = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  history: <><path d="M3 10a9 9 0 1 1 1.3 7m-1.6-7 .4-5m-.4 5h5M12 7v5l4 2"/></>,
  inbox: <><path d="M4 5h16l2 10v4H2v-4z"/><path d="M3 14h5l2 3h4l2-3h5"/></>,
  panels: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></>,
  play: <><path d="m7 4 12 8-12 8z"/></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v5m10-5v5M3 11h18"/></>,
  timer: <><circle cx="12" cy="14" r="7.5"/><path d="M9 2h6m-3 0v4m4.7.9 1.8-2M12 14l3-3"/></>,
  box: <><path d="m12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5m-9 5v10m-5-17 9 5"/></>,
  layers: <><path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/></>,
  spark: <><path d="m12 3 1.8 6.2L20 11l-6.2 1.8L12 19l-1.8-6.2L4 11l6.2-1.8zM19 2v4m-2-2h4"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/></>,
  book: <><path d="M4 5c3-1 6-1 8 1 2-2 5-2 8-1v14c-3-1-6-1-8 1-2-2-5-2-8-1zM12 6v14"/></>,
  truck: <><path d="M2 5h12v12H2zM14 9h4l4 5v3h-8"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/></>,
  shield: <><path d="m12 3 8 3v6c0 5-4 8-8 10-4-2-8-5-8-10V6z"/><path d="m8 12 3 3 5-6"/></>,
  check: <><path d="m5 12 4 4L19 6"/></>,
  mail: <><rect x="2.5" y="4.5" width="19" height="15" rx="2"/><path d="m3 6 9 7 9-7"/></>,
  x: <><path d="m6 6 12 12M18 6 6 18"/></>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-9h.01"/></>,
  network: <><path d="M5 17l7-12 7 12H5"/><circle cx="12" cy="5" r="2"/><circle cx="5" cy="17" r="2"/><circle cx="19" cy="17" r="2"/></>,
  upload: <path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>,
};

export function Icon({name}: {name: keyof typeof glyphs}) {
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{glyphs[name]}</svg>;
}

export function Heading({icon, children, count}: {icon: keyof typeof glyphs; children: ReactNode; count?: number}) {
  return <div className="card-heading"><h2 className="card-title"><Icon name={icon}/>{children}</h2>
    {count != null && <span className="small-count">{count}</span>}</div>;
}

export function Dialog({title, label, close, children}: {title: string; label: string; close: () => void; children: ReactNode}) {
  const ref = useRef<HTMLDialogElement>(null);
  const heading = useId();
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return <dialog ref={ref} aria-labelledby={heading} onCancel={close} onClick={e => { if (e.target === ref.current) close(); }}>
    <div className="dialog-inner"><button className="close" aria-label="Close dialog" onClick={close}><Icon name="x"/></button>
      <div className="overline">{label}</div><h2 id={heading}>{title}</h2>{children}</div>
  </dialog>;
}
