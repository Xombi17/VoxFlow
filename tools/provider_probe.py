#!/usr/bin/env python3
"""Validate and optionally exercise an explicitly selected ASR provider.

Configuration-only probes never make a network request. A live request needs
both ``--allow-network`` and an explicit fixture; output is an allowlisted
provider/policy status and never contains endpoint, credential, audio,
transcript, response-body, or filesystem-path data.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import wave
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError

from voxflow.audio.artifacts import AudioArtifact
from voxflow.core.jobs import DictationJobRunner
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.config import (
    NetworkPolicy,
    ProviderKind,
    ProviderSelectionSnapshot,
    RemoteProviderConfig,
)
from voxflow.providers.remote_asr import RemoteASRProvider, UrllibRemoteTransport


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate VoxFlow provider configuration without network access. "
            "Live requests require --allow-network and --fixture."
        )
    )
    parser.add_argument("--json", action="store_true", help="emit the safe JSON result")
    parser.add_argument("--provider", choices=("local", "remote"), default="local")
    parser.add_argument("--model", default="local-default", help="portable model ID")
    parser.add_argument("--endpoint", help="remote HTTP(S) endpoint")
    parser.add_argument(
        "--network-policy",
        choices=tuple(policy.value for policy in NetworkPolicy),
        default=NetworkPolicy.LOCAL_ONLY.value,
    )
    parser.add_argument("--credential-env", help="environment variable name, never a token value")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--fixture", type=Path, help="WAV fixture for an opted-in live request")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="explicitly permit a live request when --fixture is also supplied",
    )
    args = parser.parse_args(argv)

    try:
        selection = _selection_from_args(args)
    except (TypeError, ValueError, ValidationError):
        return _emit(
            {
                "status": "error",
                "error_code": "invalid_config",
                "message": "provider configuration is invalid",
            }
        )

    output: dict[str, Any] = {
        **selection.to_safe_diagnostic(),
        "capability_status": "offline_ready"
        if selection.provider_kind is ProviderKind.LOCAL
        else "configured_no_network",
        "error_code": None,
        "network_request_made": False,
    }
    if selection.provider_kind is ProviderKind.REMOTE:
        if selection.network_policy is not NetworkPolicy.REMOTE_EXPLICIT:
            output.update(
                capability_status="blocked",
                error_code="network_policy_rejected",
                message="select remote_explicit policy before enabling remote ASR",
            )
        elif args.allow_network and args.fixture is not None:
            output.update(_run_live_probe(selection, args.fixture))
        elif args.allow_network:
            output["capability_status"] = "network_opt_in_ready"
            output["message"] = "provide an explicit WAV fixture to run the opted-in smoke request"
        else:
            output["message"] = "configuration validated; no network request was made"
    return _emit(output)


def _selection_from_args(args: argparse.Namespace) -> ProviderSelectionSnapshot:
    if args.provider == "local":
        if args.endpoint is not None or args.credential_env is not None:
            raise ValueError("local providers do not accept remote settings")
        return ProviderSelectionSnapshot.local(model_id=args.model)
    remote = RemoteProviderConfig(
        model_id=args.model,
        endpoint=args.endpoint or "",
        transport_timeout_seconds=args.timeout,
        credential_env_var=args.credential_env,
    )
    return remote.to_selection(network_policy=NetworkPolicy(args.network_policy))


def _run_live_probe(selection: ProviderSelectionSnapshot, fixture: Path) -> dict[str, object]:
    try:
        artifact = _read_wav_artifact(fixture)
        provider = RemoteASRProvider(selection, transport=UrllibRemoteTransport())
        snapshot = asyncio.run(
            DictationJobRunner(provider, artifact, config=selection, job_id="provider-probe").run()
        )
    except (OSError, ValueError, wave.Error):
        return {
            "capability_status": "error",
            "error_code": "fixture_invalid",
            "network_request_made": False,
            "message": "the supplied fixture is unavailable or unsupported",
        }
    return {
        "capability_status": snapshot.state.value,
        "error_code": snapshot.error_code,
        "network_request_made": snapshot.error_code
        not in {"network_disabled", "credential_missing"},
    }


def _read_wav_artifact(path: Path) -> AudioArtifact:
    if not path.is_file():
        raise OSError("fixture unavailable")
    wav_bytes = path.read_bytes()
    with wave.open(str(path), "rb") as wav_file:
        audio_format = AudioFormat(wav_file.getframerate(), wav_file.getnchannels())
        frame_count = wav_file.getnframes()
    return AudioArtifact(
        path=path,
        audio_sha256=hashlib.sha256(wav_bytes).hexdigest(),
        source_format=audio_format,
        frame_count=frame_count,
        duration_ms=max(1, (frame_count * 1000) // audio_format.sample_rate),
        wav_byte_count=len(wav_bytes),
    )


def _emit(output: dict[str, object]) -> int:
    print(json.dumps(output, sort_keys=True))
    return 0 if output.get("status") != "error" else 2


if __name__ == "__main__":
    raise SystemExit(main())
