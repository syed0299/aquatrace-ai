# AquaTrace AI: 4-minute demo script

Start the app: `./run_demo.sh`, then open http://localhost:8000. Select the newest **LIVE** run.

## 1. The problem (20 s), full-Bay view
"A satellite image only shows where debris *was*. Currents and wind keep moving it, and cleanup boats are
limited. AquaTrace answers: where is it likely now, where will it be in 24–48 hours, where did it come from,
and how do we reach it?"

## 2. Live, not a video: answer the "impossible" objection head-on (40 s)
- Point at the red **LIVE** badge: "issued now · latest satellite pass X hours ago".
- "No satellite can film every bottle. NASA's PACE passes over the Bay once a day, and its near-real-time data
  is online about 3 hours later. When the sky is clear we detect likely floating-debris patches. Our drift
  model then carries each one forward, so the map shows where it most likely is *now*, even under clouds."
- Hover a grey ring → dashed line → hotspot: "seen by the satellite here, drifted to here since."

## 3. Detect (40 s)
- Click the top hotspot. Show the satellite image and the magenta anomaly overlay.
- "An AI model trained on MARIDA, a public labelled marine-debris dataset, reaches **94.1 % accuracy** and
  **F1 0.93 for floating material** on held-out test data. It rejects ships, wakes, waves and clouds."
- Open **Model trust** (top right): "When it says 80 %, it's right at least that often. We checked calibration, as
  promised on our deck."

## 4. Forecast + source (50 s)
- Press **Space** (or ▶): particles drift to +48 h while the currents flow underneath. "300 particles per patch. The
  cone is our uncertainty, and it's honest: on a month of real buoys we never tuned on, the buoy ended up inside
  the 48-hour cone **86 % of the time**."
- "Median error **17 km at 24 h, 30 km at 48 h**, 59 % better than assuming it stays put. Adding wind to
  currents cut the 48-hour error from 37 to 30 km."
- Purple dashed line (in the drawer, "Where it came from"): "We also run the model **backwards**. This patch traces back to the Chennai rivers,
  which tells authorities where to stop plastic *before* it reaches the sea."

## 5. Act (40 s)
- **Cleanup route** (ship button) from a port → the dashed navy route with numbered stops. "The boat is sent to where each patch *will be* when it
  arrives, not where the satellite saw it. Here it saves chasing X km of drift."
- Read one recommended action: "send a shoreline team to … within 6 h".
- **What-if** (crosshair in the right toolbar): click the sea → instant forecast. "Useful for an oil spill or a cyclone."

## 6. Close (10 s)
"See the problem. Predict its next move. Act first. Built on free NASA and ESA data, updated daily, ready to
scale from this Bay of Bengal pilot to all of India."

---

## Likely judge questions

**"Showing debris live is impossible."**
Agreed if you mean a live video. We never claim that. We show *potential* floating-debris hotspots from the
latest satellite pass (about 3 hours old), move them to their likely position now with a validated drift
model, and forecast 48 hours ahead. Oil-spill trajectory forecasting and sargassum outlooks use the same
approach: satellite detection plus a drift forecast.

**"How does it identify plastic? How can a satellite photo be that clear?"** (show slide 11)
- The clear picture in the app is a background map (Esri basemap), not a photo of debris, and the dots are our forecast
  particles. The real satellite data looks like slide 11, left: 20 m squares, with a hotspot a handful of pixels wide.
- No satellite sees a bottle. It measures how much sunlight each pixel reflects in each colour. Water absorbs
  near-infrared, so the sea is dark there; anything floating reflects it back. The Floating Debris Index measures that
  excess (Biermann et al., 2020).
- The shape across colours is a fingerprint: algae jumps at the red edge, debris is flat and bright, and ships are
  bright even in short-wave infrared. Our Visakhapatnam hotspot has the debris shape; our Hooghly patch has the
  vegetation shape.
- The AI learned those fingerprints from expert-labelled scenes (MARIDA). On a Gulf of Honduras scene it never saw,
  it found 20 of 20 labelled debris pixels with 0 false alarms on 69 water pixels; on the whole test set it finds 89%.
- Field proof that this works: in the Plastic Litter Project, plastic targets placed in the sea off Greece were
  detected in Sentinel-2 imagery (Topouzelis et al., 2019).
- What we don't claim: that a given hotspot *is* plastic. It's potential floating material with a type and a
  confidence; confirming it needs a boat or drone, which is our Phase 2.

**Can PACE really see plastic at 1.2 km?**
Not single items. It flags regions where floating material changes the spectrum. That's why PACE hotspots
have lower confidence, and why Sentinel-2 (10–20 m) plus the AI model is the higher-resolution check.

**Is 94.1 % accuracy real?**
It's on MARIDA's official test split. Every model and feature choice was made on the validation split first.
Most pixels are water, so we also report debris F1 (0.78) and floating-material F1 (0.93). MARIDA's scenes
aren't from India. Local ground truth is Phase 2.

**Why two models?**
Gradient boosting is best at telling water types, waves and wakes apart; Extra Trees is best at finding debris
and its confidence is well calibrated. So Extra Trees decides "floating material or not" and the pair votes on
everything else. That raised accuracy from 91.9 % to 94.1 % and debris F1 from 0.75 to 0.78.

**How do you know the drift forecast works?**
We tuned it on January 2025 buoys and tested on February buoys it never saw: median error 17 km at 24 h and
30 km at 48 h, versus 37 and 74 km for "it stays put". And the uncertainty cone is checked too: the real buoy
fell inside the 90 % cone 79 % of the time at 24 h and 86 % at 48 h (before our fix, only 5 %).

**How does source tracking work?**
The same particle model, run backwards 72 h. If most back-tracked particles reach a coast near a river mouth,
that's the likely source.

**What does the risk score use?**
35 % detection confidence, 25 % proximity of the predicted track to sensitive sites and coast, 15 % beaching
likelihood, 15 % recurrence across passes, 10 % forecast certainty.
