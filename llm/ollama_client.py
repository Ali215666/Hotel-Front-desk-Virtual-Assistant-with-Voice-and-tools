"""
Ollama client for interacting with local LLM models.
"""

import requests
from typing import Optional, AsyncGenerator
import httpx
import asyncio
import json


class OllamaClient:
    """Client for communicating with Ollama API."""
    
    def __init__(self, model_name: str = "hotel-qwen", base_url: str = "http://localhost:11434"):
        """
        Initialize the Ollama client.
        
        Args:
            model_name: Name of the Ollama model to use
            base_url: Base URL for Ollama API
        """
        self.model_name = model_name
        self.base_url = base_url
        self.generate_url = f"{base_url}/api/generate"
        # Local CPU inference can be slow on first run; use generous timeouts.
        self.sync_timeout_seconds = 300
        self.stream_timeout_seconds = 300
        self.keep_alive = "30m"
        self.options = {
            "num_ctx": 2048,
            "temperature": 0.2,
        }
        self._sync_session = requests.Session()
        self._async_client: Optional[httpx.AsyncClient] = None
        self._async_client_lock = asyncio.Lock()
    
    def generate(self, prompt: str) -> str:
        """
        Generate a response from the model.
        
        Args:
            prompt: Constructed prompt for the model
            
        Returns:
            str: Assistant text output only
        """
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": self.options,
        }
        
        try:
            response = self._sync_session.post(
                self.generate_url,
                json=payload,
                timeout=self.sync_timeout_seconds
            )
            response.raise_for_status()
            
            result = response.json()
            return result.get('response', '').strip()
        
        except requests.Timeout:
            return (
                "Error: Request timed out after "
                f"{self.sync_timeout_seconds}s. Local model inference is taking too long."
            )
        
        except requests.ConnectionError:
            return "Error: Could not connect to Ollama. Ensure Ollama is running on http://localhost:11434"
        
        except requests.HTTPError as e:
            return f"Error: HTTP {e.response.status_code} - {e.response.reason}"
        
        except requests.RequestException as e:
            return f"Error: {str(e)}"
        
        except Exception as e:
            return f"Unexpected error: {str(e)}"
    
    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response from the model token-by-token.
        
        Args:
            prompt: Constructed prompt for the model
            
        Yields:
            str: Individual tokens/chunks of the response
        """
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": self.options,
        }
        
        try:
            client = await self._get_async_client()
            async with client.stream('POST', self.generate_url, json=payload) as response:
                if response.status_code != 200:
                    yield f"Error: HTTP {response.status_code}"
                    return

                async for line in response.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            if 'response' in chunk:
                                token = chunk['response']
                                if token:
                                    yield token

                            # Check if this is the final chunk
                            if chunk.get('done', False):
                                break
                        except json.JSONDecodeError:
                            continue
                        except Exception:
                            continue
        
        except httpx.TimeoutException:
            yield (
                "Error: Request timed out after "
                f"{self.stream_timeout_seconds}s. Local model inference is taking too long."
            )
        
        except httpx.ConnectError:
            yield f"Error: Could not connect to Ollama. Ensure Ollama is running on {self.base_url}"
        
        except httpx.HTTPError as e:
            yield f"Error: HTTP error occurred - {str(e)}"
        
        except Exception as e:
            yield f"Unexpected error: {str(e)}"

    async def _get_async_client(self) -> httpx.AsyncClient:
        """Lazily create a reusable async HTTP client for streaming calls."""
        if self._async_client is not None:
            return self._async_client

        async with self._async_client_lock:
            if self._async_client is not None:
                return self._async_client

            timeout = httpx.Timeout(
                timeout=self.stream_timeout_seconds,
                connect=30.0,
                write=30.0,
                pool=30.0,
            )
            self._async_client = httpx.AsyncClient(timeout=timeout)
            return self._async_client

    def prewarm(self, prompt: Optional[str] = None) -> bool:
        """
        Trigger a tiny generation to load the model into memory.

        Returns:
            bool: True when Ollama responds successfully.
        """
        payload = {
            "model": self.model_name,
            "prompt": prompt or "ping",
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                **self.options,
                "num_predict": 1,
                "temperature": 0,
            },
        }

        try:
            response = self._sync_session.post(
                self.generate_url,
                json=payload,
                timeout=45,
            )
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False
