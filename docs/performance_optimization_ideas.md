# WellNest — Performance / Speed Optimization Ideas

> Captured from a ChatGPT discussion on making the scribe faster **without raising GPU cost**,
> plus WellNest-specific analysis. **Ideas, not committed work.**

## The measured baseline (our real numbers)
- GPU: **Nvidia T4 on Modal**, omniASR **CTC** variant.
- 86.6 min audio → **~382 s transcription (~13.6× realtime)**; interpret ~26 s; SOAP ~8 s.
- **omniASR cost is already tiny: ~$0.032 / audio-hour (measured).** The bottleneck is *latency*, not cost.

## The key framing (important)
Optimizing transcription **improves UX/latency, not the bill** — omniASR is already ~3¢/hour.
**The money is in GPT-5.4** (the two-call → one-call flip, T10). So treat the ideas below as
**latency / UX** work, and keep cost focus on the LLM line.

## The ideas, ranked for WellNest
| Idea | Verdict for us | Value |
|---|---|---|
| **Streaming / chunked transcription** (transcribe while recording) | **Best UX win.** Note ready seconds after the visit instead of a 6-min wait on long recordings. Real architecture change (client chunks audio every ~30–60 s → progressive transcription). | 🔴 high UX |
| **TensorRT FP16 for the CTC encoder** | Good fit — CTC = encoder + linear + CTC decode, **no autoregressive decoder**, so TensorRT optimizes the heavy part well. Realistic **~2–3× (13.6× → 25–40×)**, which cuts latency *and* GPU-seconds. Path: PyTorch → ONNX → TensorRT FP16 engine, dynamic shapes (30 s → 2 h). **Validate Patois accuracy** before shipping. | 🟡 med (deploy effort) |
| **Batching** (multiple doctors' chunks per GPU batch) | Helps **at scale** with many concurrent doctors — higher GPU utilisation, lower cost/transcription. Modal already autoscales; batch inside a warm container when concurrency is high. | 🟡 med (at scale) |
| **Optimize chunk size / overlap** | We already chunk (`chunk_seconds=30`). Smaller overlapping chunks → better parallelism + failure recovery. Low effort tweak. | 🟢 low |
| **INT8 quantization** | **Avoid for now** — accuracy risk on medical + Patois. FP16 is the safe stop. | ⛔ skip (accuracy) |
| **CTranslate2 / faster Whisper runtime** | **N/A** — omniASR is a fairseq2/omnilingual CTC model, **not Whisper**. ONNX/TensorRT is the right path, not CT2. | ⛔ n/a |
| **Off-peak batch processing** | A clinic wants real-time; little benefit. | 🟢 skip |
| **CPU/GPU split** | Already true — interpret/SOAP run on Azure GPT (not our GPU) and are fast (8–26 s). Don't optimize them. | ✅ already fine |

## Honest recommendation (priority order)
1. **Don't over-invest in speed** — omniASR is already cheap and fast enough for a pilot.
2. **Cost first: do T10 (GPT pipeline flip).** That's where the money is; transcription isn't.
3. **UX next: streaming transcription** — highest perceived-speed win, but a real build; do it after the core is validated.
4. **TensorRT FP16** — a solid medium-term latency+cost win given the CTC architecture; gate on a Patois accuracy check. FP16 only.
5. Chunk-size tweak + batching-at-scale when concurrency justifies it.

## Guardrail
Any speed change must be validated against **Patois / Jamaican-English accuracy** — that's the moat,
and shaving milliseconds isn't worth a word-error-rate regression.
