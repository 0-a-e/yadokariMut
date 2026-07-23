#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek API client module (OpenAI-compatible) supporting both real-time and Batch APIs."""

import io
import json
import logging
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Setup logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL")

_TERMINAL_STATUSES = {"completed", "failed", "expired", "cancelled"}


class DeepSeekClient:
    """Standard client for real-time DeepSeek API completions."""

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url or DEEPSEEK_BASE_URL
        self.model = model or DEEPSEEK_MODEL

        if not self.api_key or "your_deepseek_api_key" in self.api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set or invalid.")
        if not self.base_url:
            raise ValueError("DEEPSEEK_BASE_URL environment variable is not set.")
        if not self.model:
            raise ValueError("DEEPSEEK_MODEL environment variable is not set.")

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.0, timeout: int = 30) -> str:
        """Executes a real-time chat completion request.

        Args:
            system_prompt: System role message.
            user_prompt: User role message.
            temperature: Lower values (e.g. 0.0) are more deterministic.
            timeout: Request timeout in seconds.

        Returns:
            The completion response text, or None if failed.
        """
        if not self.client:
            logger.error("DeepSeek client is not initialized due to missing API key")
            return None

        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                top_p=0.8,
                timeout=timeout,
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"DeepSeek API request failed: {e}")
            return None


class DeepSeekBatchClient:
    """Client for DeepSeek Batch API using OpenAI-compatible Batch File API."""

    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url or DEEPSEEK_BASE_URL
        self.model = model or DEEPSEEK_MODEL

        if not self.api_key or "your_deepseek_api_key" in self.api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set or invalid.")
        if not self.base_url:
            raise ValueError("DEEPSEEK_BASE_URL environment variable is not set.")
        if not self.model:
            raise ValueError("DEEPSEEK_MODEL environment variable is not set.")

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def build_batch_jsonl(self, tasks: list[dict]) -> str:
        """Builds a JSONL string from classification tasks.

        Args:
            tasks: A list of dicts, each containing:
                   - "custom_id": unique identifier (e.g. campaign ID)
                   - "system_prompt": instructions for the model
                   - "user_prompt": the query details

        Returns:
            JSONL format string.
        """
        lines = []
        for task in tasks:
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": task["system_prompt"]},
                    {"role": "user", "content": task["user_prompt"]},
                ],
                "temperature": 0.0,
                "top_p": 0.8,
            }
            line = json.dumps({
                "custom_id": str(task["custom_id"]),
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }, ensure_ascii=False)
            lines.append(line)

        return "\n".join(lines) + "\n"

    def submit_batch(
        self,
        jsonl_content: str,
        endpoint: str = "/v1/chat/completions",
        completion_window: str = "24h",
    ) -> str:
        """Uploads JSONL content and creates a Batch job.

        Args:
            jsonl_content: The JSONL formatted tasks string.
            endpoint: API endpoint (default /v1/chat/completions).
            completion_window: Maximum time frame for batch execution.

        Returns:
            batch_id (str) or None if submission failed.
        """
        if not self.client:
            logger.error("DeepSeek client is not initialized due to missing API key")
            return None

        try:
            logger.info("Uploading JSONL file for batch processing...")
            file_obj = self.client.files.create(
                file=("batch_input.jsonl", io.BytesIO(jsonl_content.encode("utf-8"))),
                purpose="batch",
            )
            logger.info(f"File uploaded successfully. file_id={file_obj.id}")

            logger.info("Creating batch job on DeepSeek...")
            batch = self.client.batches.create(
                input_file_id=file_obj.id,
                endpoint=endpoint,
                completion_window=completion_window,
            )
            logger.info(f"Batch job created. batch_id={batch.id}")
            return batch.id
        except Exception as e:
            logger.error(f"Failed to submit Batch job: {e}")
            return None

    def wait_for_completion(
        self, batch_id: str, poll_interval: int = 15, timeout: int = 1800
    ) -> tuple[str, object]:
        """Polls the Batch job status until it reaches a terminal state or times out.

        Args:
            batch_id: The Batch job ID.
            poll_interval: Seconds between retrieve status requests.
            timeout: Maximum seconds to wait.

        Returns:
            A tuple (status: str, batch_object) or ("failed/timeout", None)
        """
        if not self.client:
            logger.error("DeepSeek client is not initialized")
            return "failed", None

        logger.info(f"Waiting for Batch job {batch_id} (timeout={timeout}s)...")
        start = time.monotonic()
        last_status = None

        while True:
            elapsed = time.monotonic() - start
            if elapsed > timeout:
                logger.error(f"Batch job {batch_id} timed out after {timeout}s")
                return "timeout", None

            try:
                batch = self.client.batches.retrieve(batch_id=batch_id)
                status = batch.status

                if status != last_status:
                    logger.info(f"Batch {batch_id} status: {status} (elapsed={elapsed:.0f}s)")
                    last_status = status

                if status in _TERMINAL_STATUSES:
                    logger.info(f"Batch {batch_id} completed with status: {status}")
                    return status, batch

            except Exception as e:
                logger.warning(f"Error retrieving batch status: {e}. Retrying...")

            time.sleep(poll_interval)

    def get_results(self, batch_id: str) -> dict[str, str]:
        """Downloads the Batch results and returns them mapped by custom_id.

        Args:
            batch_id: The completed Batch job ID.

        Returns:
            A dict of {custom_id: response_content}. Empty if failed.
        """
        if not self.client:
            logger.error("DeepSeek client is not initialized")
            return {}

        results = {}
        try:
            batch = self.client.batches.retrieve(batch_id=batch_id)
            output_file_id = batch.output_file_id
            
            if not output_file_id:
                logger.warning(f"No output_file_id found for batch {batch_id} (status: {batch.status})")
                return {}

            logger.info(f"Downloading results from output_file_id={output_file_id}")
            content = self.client.files.content(output_file_id)
            
            for line in content.text.strip().split("\n"):
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    custom_id = row.get("custom_id")
                    response = row.get("response", {})
                    if response.get("status_code") == 200:
                        body = response.get("body", {})
                        choices = body.get("choices", [])
                        if choices:
                            message = choices[0].get("message", {})
                            results[custom_id] = message.get("content", "").strip()
                        else:
                            logger.warning(f"No completion choices in response for custom_id={custom_id}")
                    else:
                        logger.warning(f"Request failed for custom_id={custom_id}: status={response.get('status_code')}")
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse result line: {line[:100]}...")
            
            logger.info(f"Successfully processed {len(results)} results from batch {batch_id}")
        except Exception as e:
            logger.error(f"Failed to download Batch results: {e}")

        return results
