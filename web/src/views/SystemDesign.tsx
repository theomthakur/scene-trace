export default function SystemDesign() {
  const box = (x: number, y: number, w: number, label: string, sub: string) => <g><rect x={x} y={y} width={w} height={54} rx={8} className="d-box" /><text x={x + w / 2} y={y + 23} textAnchor="middle" className="d-t">{label}</text><text x={x + w / 2} y={y + 41} textAnchor="middle" className="d-s">{sub}</text></g>
  return (
    <div className="doc">
      <h1>System design</h1>
      <p className="lead">A video investigation tool helps a reviewer answer what happened, where, and which evidence supports it. It supports review. It does not decide intent, blame, identity or safety compliance.</p>
      <h2>Flow</h2>
      <svg viewBox="0 0 980 190" role="img" aria-label="Pipeline: video to decode, detector, tracker, rules, events and evidence, review interface" className="diagram">
        {box(10, 20, 120, 'Video', 'hash, probe')}{box(160, 20, 130, 'Decode', 'PyAV, pts in ms')}{box(320, 20, 150, 'Detector', 'Faster R-CNN COCO')}{box(500, 20, 130, 'Tracker', 'IoU + Hungarian')}{box(660, 20, 150, 'Temporal rules', 'zones, dwell, gaps')}{box(840, 20, 130, 'Evidence', 'frames, clips')}
        {box(160, 120, 150, 'SQLite (WAL)', 'runs, events, reviews')}{box(340, 120, 150, 'Worker', 'lease, cancel, recover')}{box(520, 120, 130, 'FastAPI', 'contracts, ranges')}{box(680, 120, 150, 'React review UI', 'timeline, evidence')}
        <path d="M130 47h30M290 47h30M470 47h30M630 47h30M810 47h30M235 74v46M415 74v46M585 74v46M755 74v46" className="d-line" />
      </svg>
      <h2>Technology choices</h2>
      <ul>
        <li><strong>Detector.</strong> torchvision Faster R-CNN MobileNetV3-Large 320 FPN with COCO weights, on CPU by default. Chosen for manageable complexity, not best accuracy. Weights are not trained or fine-tuned here.</li>
        <li><strong>Tracker.</strong> A custom baseline: per-class tracks, constant-velocity prediction over real elapsed time, IoU gate 0.20, Hungarian assignment. It is not ByteTrack or DeepSORT and does no re-identification.</li>
        <li><strong>Time.</strong> Integer milliseconds from presentation timestamps. Sampling is by time, so variable frame rates do not shift events.</li>
        <li><strong>Coordinates.</strong> Normalized xyxy in the upright frame. The UI maps pointers through the video content rectangle, so letterboxing does not skew zones.</li>
        <li><strong>Storage.</strong> SQLite in WAL mode with a durable job table; artifacts live in per-attempt directories published by an atomic manifest.</li>
      </ul>
      <h2>Data model</h2>
      <p>Video, ZoneSet (immutable versions), Run (frozen config and zones), Observation, Event (with evidence references and uncertainty flags), Review (revisioned). Detector confidence is stored separately from event correctness and is never presented as a calibrated probability.</p>
      <h2>Failure handling and recovery</h2>
      <ul>
        <li>Invalid, oversized, non-video or untimed input is rejected before processing with an explicit code.</li>
        <li>A worker claims one queued run with a lease and heartbeats. A stale lease becomes <em>interrupted</em>; restarting creates a fresh attempt and never appends to an old one.</li>
        <li>Artifacts are written first, the manifest is published atomically, and only then does the database say completed.</li>
        <li>Missing weights fail loudly. There is no fallback to fixtures or random weights.</li>
        <li>Zero events is not "incident-free": quality flags (sparse detections, long gaps, timestamp fallback) travel with every run.</li>
      </ul>
      <h2>Limitations</h2>
      <ul>
        <li>A general COCO detector misses and mislabels objects, especially small, occluded or unusual ones.</li>
        <li>The tracker fragments identities in crowded scenes at low sampling rates.</li>
        <li>Image overlap is not physical clearance; a stationary object is not called unattended or abandoned.</li>
        <li>Evaluation data is small. See the Evaluation view for exact denominators.</li>
      </ul>
    </div>
  )
}
