# Walkthrough

## First run

1. Install the [local prerequisites and dependencies](../README.md#run-locally), download the sample footage, and start the app with `scripts/dev.sh`. Open `http://127.0.0.1:5173`.
2. In **Review**, open **Switch or upload a video** if a video is already selected. Choose `var/candidates/pedestrian_area.webm` and click **Upload**. The API saves the original and makes a browser-playable copy.
3. Select **Draw zone** with **Restricted** selected. On the sample, draw a rectangle roughly from 35% to 65% of the video's width and from 60% to 95% of its height, measured from the top left. Select **Finish polygon**, then **Save zones**.
4. Select **Process video**. The worker samples frames, detects and tracks objects, and applies the rules using the saved zone. Wait for **Completed**.
5. In **Moments to review**, choose a timestamp and check the supporting frames. Click a frame to jump to its timestamp. Use **Show boxes around detected objects** to compare the detections with the footage. Select a verdict and save it. Expand **Export report** below the video to choose HTML, Markdown, or JSON.
6. Open **Evaluation** for the benchmark results, sample sizes and limitations. Open **System Design** to see how the API, worker, storage and UI fit together.
7. Stop the local app with `scripts/dev.sh stop`. For the separate read-only demo build, see the [deployment guide](DEPLOYMENT.md#1-read-only-demo-static).

## 90-second demo script
1. **(10 s) Start.** `scripts/dev.sh`, open http://127.0.0.1:5173. Point at the green "Live backend" badge: this is the live app, not canned results. (`?mode=demo` shows a separate amber "Static demo" badge.)
2. **(15 s) Upload.** Choose `pedestrian_area.webm`. Say: "A browser-playable copy is made, and the original is stored untouched with its SHA-256."
3. **(20 s) Zones.** Click Draw zone, click four points on the video, Finish polygon, Save zones. Say: "Zones are normalized coordinates and versioned. Editing a zone makes a new version and a new run."
4. **(20 s) Process.** Click Process video. Say: "A worker claims the job with a lease. The COCO detector runs on real decoded frames, about 70 ms per frame on CPU. Cancel works between frames, and a killed worker is recovered as interrupted."
5. **(20 s) Inspect.** Click an event. Show the timeline segment, boxes and zone over the video, the three evidence frames (click one to jump to that timestamp), the rule text, and any uncertainty flags.
6. **(5 s) Review and export.** Mark Confirmed with a note, save, then open the HTML report: it carries the video and manifest hashes and the limitations.

If asked about results: "Fixtures pass all 11 truth events. On real footage the numbers rest on 1 to 3 events from two CC0 clips, so I report denominators, not claims."

## Architecture in plain language
- **Video in:** the file is probed with ffprobe (size, duration, rotation, timestamps) and rejected early if it is not a video, too big, too long or has no usable timing.
- **Decode:** PyAV gives each frame its real presentation time in milliseconds. Frames are picked by time (5 per second), not by counting, so variable frame rates do not shift events. Frames are turned upright and shrunk to at most 960 px.
- **Detect and track:** the detector returns boxes in normalized coordinates. The tracker links boxes over time into tracks with temporary IDs.
- **Rules:** versioned rules turn tracks into event intervals: dwell in a zone, standing still, overlapping a passage. A short gap or a brief flicker does not create or split an event, and missed time never counts as dwell.
- **Evidence:** for every event the original video is decoded again, boxes are drawn on the original-resolution frames, and a padded clip is cut. Frame times snap to real observation times.
- **Storage and recovery:** files are written first and a manifest is published atomically. Only then does SQLite say the run is completed. If a worker dies, its lease expires, the run becomes interrupted, and restarting recomputes in a fresh attempt.
- **UI:** the player draws overlays from normalized coordinates through the video's visible rectangle, so letterboxing does not skew clicks. Boxes are painted only within a tolerance of a real sample time.

## What is substantive CV here, and what is not
Substantive: real inference, timestamp and coordinate handling through resize and rotation, tracking with gating and lifecycle, temporal rules with explicit persistence, and evidence tied to stored observations. Not novel: the detector is off the shelf and the tracker is a baseline. Personal contribution is pipeline integration, temporal logic, evaluation and the product workflow.
