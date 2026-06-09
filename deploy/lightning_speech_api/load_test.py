"""Concurrent load tester for the WellNest speech API.

Example:
    python load_test.py ^
      --url https://example.modal.run/transcribe/mms/file ^
      --file /path/to/audio.mpeg ^
      --api-key replace-me ^
      --backend mms ^
      --target-lang jam ^
      --requests 10 ^
      --concurrency 10 ^
      --warm-first
"""

from __future__ import annotations

import argparse
import io
import json
import math
import mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean
from threading import Barrier
from time import perf_counter, sleep
from typing import Any

import requests


T4_COST_PER_SECOND_USD = 0.000164


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    fraction = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "count": 0,
            "avg": None,
            "min": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    return {
        "count": len(values),
        "avg": mean(values),
        "min": min(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values),
    }


def _format_ms(summary: dict[str, float | None]) -> str:
    if not summary["count"]:
        return "n/a"
    return (
        f"avg={summary['avg']:.1f} ms  "
        f"p50={summary['p50']:.1f} ms  "
        f"p95={summary['p95']:.1f} ms  "
        f"p99={summary['p99']:.1f} ms  "
        f"max={summary['max']:.1f} ms"
    )


def _derive_warm_url(transcribe_url: str) -> str | None:
    for suffix in ("/transcribe/mms/file", "/transcribe/whisper/file", "/transcribe/file"):
        if transcribe_url.endswith(suffix):
            return transcribe_url[: -len(suffix)] + "/warm"
    return None


def _build_headers(api_key: str, bearer_token: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


def _build_payload(args: argparse.Namespace) -> dict[str, str]:
    payload = {
        "backend": args.backend,
        "device": args.device,
    }
    if args.model_id:
        payload["model_id"] = args.model_id
    if args.backend == "mms":
        payload["target_lang"] = args.target_lang
        payload["chunk_seconds"] = str(args.chunk_seconds)
        payload["batch_size"] = str(args.batch_size)
    else:
        if args.language:
            payload["language"] = args.language
        payload["task"] = args.task
        payload["compute_type"] = args.compute_type
        payload["beam_size"] = str(args.beam_size)
    return payload


def _request_once(
    *,
    index: int,
    url: str,
    headers: dict[str, str],
    payload: dict[str, str],
    audio_bytes: bytes,
    audio_name: str,
    content_type: str,
    timeout_s: int,
    barrier: Barrier | None,
    stagger_ms: int,
) -> dict[str, Any]:
    if barrier is not None:
        barrier.wait()
    if stagger_ms > 0:
        sleep((index * stagger_ms) / 1000)

    started = perf_counter()
    try:
        audio_handle = io.BytesIO(audio_bytes)
        response = requests.post(
            url,
            headers=headers,
            data=payload,
            files={"file": (audio_name, audio_handle, content_type)},
            timeout=timeout_s,
        )
        elapsed_ms = (perf_counter() - started) * 1000
        result: dict[str, Any] = {
            "index": index,
            "status_code": response.status_code,
            "client_elapsed_ms": elapsed_ms,
        }
        try:
            body = response.json()
        except ValueError:
            body = {"raw_text": response.text[:1000]}
        result["body"] = body
        result["ok"] = bool(body.get("ok")) and response.ok
        if result["ok"]:
            server_total_ms = body.get("total_ms")
            if isinstance(server_total_ms, (int, float)):
                result["server_total_ms"] = float(server_total_ms)
                result["client_overhead_ms"] = elapsed_ms - float(server_total_ms)
            inference_ms = body.get("inference_ms")
            if isinstance(inference_ms, (int, float)):
                result["inference_ms"] = float(inference_ms)
            preprocessing_ms = body.get("preprocessing_ms")
            if isinstance(preprocessing_ms, (int, float)):
                result["preprocessing_ms"] = float(preprocessing_ms)
            audio_seconds = body.get("audio_seconds")
            if isinstance(audio_seconds, (int, float)):
                result["audio_seconds"] = float(audio_seconds)
            realtime_factor = body.get("realtime_factor")
            if isinstance(realtime_factor, (int, float)):
                result["realtime_factor"] = float(realtime_factor)
            transcript = (body.get("transcript") or "").strip()
            result["transcript_chars"] = len(transcript)
        else:
            result["error"] = body.get("detail") or body.get("raw_text") or response.text[:300]
        return result
    except Exception as exc:  # noqa: BLE001
        return {
            "index": index,
            "ok": False,
            "status_code": None,
            "client_elapsed_ms": (perf_counter() - started) * 1000,
            "error": str(exc),
        }


def _print_result_table(results: list[dict[str, Any]]) -> None:
    print("\nPer-request results")
    print("-" * 88)
    print(f"{'#':>3}  {'ok':>2}  {'status':>6}  {'client_ms':>10}  {'server_ms':>10}  {'overhead_ms':>11}  {'rtf':>8}")
    print("-" * 88)
    for result in sorted(results, key=lambda item: item["index"]):
        print(
            f"{result['index']:>3}  "
            f"{'Y' if result.get('ok') else 'N':>2}  "
            f"{str(result.get('status_code')):>6}  "
            f"{result.get('client_elapsed_ms', 0):>10.1f}  "
            f"{result.get('server_total_ms', float('nan')) if result.get('server_total_ms') is not None else float('nan'):>10.1f}  "
            f"{result.get('client_overhead_ms', float('nan')) if result.get('client_overhead_ms') is not None else float('nan'):>11.1f}  "
            f"{result.get('realtime_factor', float('nan')) if result.get('realtime_factor') is not None else float('nan'):>8.3f}"
        )
    print("-" * 88)


def main() -> int:
    parser = argparse.ArgumentParser(description="Concurrent load test for the WellNest speech API.")
    parser.add_argument("--url", required=True, help="Full transcription endpoint URL.")
    parser.add_argument("--file", required=True, help="Audio file to upload.")
    parser.add_argument("--requests", type=int, default=10, help="Total requests to send. Default: 10.")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent workers. Default: 10.")
    parser.add_argument("--timeout", type=int, default=600, help="Per-request timeout in seconds. Default: 600.")
    parser.add_argument("--stagger-ms", type=int, default=0, help="Optional stagger between request starts. Default: 0.")
    parser.add_argument("--warm-first", action="store_true", help="Call /warm before the load test.")
    parser.add_argument("--api-key", default="", help="Optional X-API-Key header value.")
    parser.add_argument("--bearer-token", default="", help="Optional bearer token.")
    parser.add_argument("--backend", default="mms", choices=["mms", "whisper"], help="Backend to test.")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"], help="Requested device.")
    parser.add_argument("--model-id", default="", help="Optional model id override.")
    parser.add_argument("--target-lang", default="jam", help="MMS target language.")
    parser.add_argument("--chunk-seconds", type=int, default=25, help="MMS chunk size.")
    parser.add_argument("--batch-size", type=int, default=4, help="MMS batch size.")
    parser.add_argument("--language", default="", help="Optional Whisper language hint.")
    parser.add_argument("--task", default="transcribe", choices=["transcribe", "translate"], help="Whisper task.")
    parser.add_argument("--compute-type", default="auto", help="Whisper compute type.")
    parser.add_argument("--beam-size", type=int, default=5, help="Whisper beam size.")
    parser.add_argument("--json-out", default="", help="Optional path to write raw JSON results.")
    args = parser.parse_args()

    audio_path = Path(args.file).expanduser().resolve()
    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")

    headers = _build_headers(args.api_key, args.bearer_token)
    payload = _build_payload(args)
    audio_bytes = audio_path.read_bytes()
    content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"

    if args.warm_first:
        warm_url = _derive_warm_url(args.url)
        if not warm_url:
            raise SystemExit("Could not derive /warm URL from --url.")
        warm_payload = {"backend": args.backend}
        if args.backend == "mms":
            warm_payload["target_lang"] = args.target_lang
        else:
            if args.model_id:
                warm_payload["model_id"] = args.model_id
            warm_payload["compute_type"] = args.compute_type
        print(f"Warming backend via {warm_url} ...")
        warm_response = requests.post(
            warm_url,
            headers=headers,
            data=warm_payload,
            timeout=args.timeout,
        )
        warm_response.raise_for_status()
        print("Warmup complete.")

    total_requests = max(args.requests, 1)
    concurrency = max(min(args.concurrency, total_requests), 1)
    barrier = Barrier(concurrency) if concurrency > 1 else None

    started = perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                _request_once,
                index=index + 1,
                url=args.url,
                headers=headers,
                payload=payload,
                audio_bytes=audio_bytes,
                audio_name=audio_path.name,
                content_type=content_type,
                timeout_s=args.timeout,
                barrier=barrier,
                stagger_ms=args.stagger_ms,
            )
            for index in range(total_requests)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    test_elapsed_s = perf_counter() - started

    successful = [result for result in results if result.get("ok")]
    failures = [result for result in results if not result.get("ok")]

    client_ms = [float(result["client_elapsed_ms"]) for result in successful]
    server_ms = [float(result["server_total_ms"]) for result in successful if result.get("server_total_ms") is not None]
    overhead_ms = [float(result["client_overhead_ms"]) for result in successful if result.get("client_overhead_ms") is not None]
    preprocess_ms = [float(result["preprocessing_ms"]) for result in successful if result.get("preprocessing_ms") is not None]
    inference_ms = [float(result["inference_ms"]) for result in successful if result.get("inference_ms") is not None]
    audio_seconds = [float(result["audio_seconds"]) for result in successful if result.get("audio_seconds") is not None]
    rtf_values = [float(result["realtime_factor"]) for result in successful if result.get("realtime_factor") is not None]

    total_server_seconds = sum(server_ms) / 1000
    total_inference_seconds = sum(inference_ms) / 1000
    total_audio_minutes = sum(audio_seconds) / 60 if audio_seconds else 0

    estimated_t4_total_usd = total_server_seconds * T4_COST_PER_SECOND_USD
    estimated_t4_inference_usd = total_inference_seconds * T4_COST_PER_SECOND_USD

    print("\nLoad test summary")
    print("-" * 88)
    print(f"URL:                {args.url}")
    print(f"File:               {audio_path}")
    print(f"Backend:            {args.backend}")
    print(f"Requests:           {total_requests}")
    print(f"Concurrency:        {concurrency}")
    print(f"Success / failure:  {len(successful)} / {len(failures)}")
    print(f"Wall-clock test:    {test_elapsed_s:.2f} s")
    if test_elapsed_s > 0:
        print(f"Throughput:         {len(successful) / test_elapsed_s:.2f} successful req/s")
    print(f"Client latency:     {_format_ms(_summary(client_ms))}")
    print(f"Server total_ms:    {_format_ms(_summary(server_ms))}")
    print(f"Queue/network gap:  {_format_ms(_summary(overhead_ms))}")
    print(f"Preprocess ms:      {_format_ms(_summary(preprocess_ms))}")
    print(f"Inference ms:       {_format_ms(_summary(inference_ms))}")
    if rtf_values:
        rtf_summary = _summary(rtf_values)
        print(
            "Realtime factor:    "
            f"avg={rtf_summary['avg']:.3f}  p50={rtf_summary['p50']:.3f}  "
            f"p95={rtf_summary['p95']:.3f}  max={rtf_summary['max']:.3f}"
        )
    print(f"Audio processed:    {sum(audio_seconds):.2f} s total ({total_audio_minutes:.2f} min)")
    print(f"Est. T4 cost total: ${estimated_t4_total_usd:.4f} (from server total_ms)")
    print(f"Est. T4 cost infer: ${estimated_t4_inference_usd:.4f} (from inference_ms only)")
    if total_audio_minutes > 0:
        print(f"Est. cost / audio min (total_ms): ${estimated_t4_total_usd / total_audio_minutes:.4f}")
    print("-" * 88)

    _print_result_table(results)

    if failures:
        print("\nFailures")
        print("-" * 88)
        for result in sorted(failures, key=lambda item: item["index"]):
            print(f"#{result['index']}: status={result.get('status_code')} error={result.get('error')}")
        print("-" * 88)

    if args.json_out:
        output_path = Path(args.json_out).expanduser().resolve()
        output_path.write_text(
            json.dumps(
                {
                    "config": {
                        "url": args.url,
                        "file": str(audio_path),
                        "backend": args.backend,
                        "requests": total_requests,
                        "concurrency": concurrency,
                        "timeout": args.timeout,
                        "stagger_ms": args.stagger_ms,
                    },
                    "summary": {
                        "successes": len(successful),
                        "failures": len(failures),
                        "wall_clock_seconds": test_elapsed_s,
                        "estimated_t4_total_usd": estimated_t4_total_usd,
                        "estimated_t4_inference_usd": estimated_t4_inference_usd,
                    },
                    "results": sorted(results, key=lambda item: item["index"]),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Saved raw results to {output_path}")

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
