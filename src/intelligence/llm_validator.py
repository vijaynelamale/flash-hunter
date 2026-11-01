"""Cloud LLM verification engine using Gemini 2.5 Flash with Groq fallback."""

import json
import logging
from typing import List, Optional
import httpx
from pydantic import BaseModel, Field
from src.config_loader import TargetItem
from src.scraper.product_fetcher import ParsedProduct

logger = logging.getLogger(__name__)


class DealVerificationResult(BaseModel):
    """Strict JSON schema output for deal authenticity verification."""

    is_authentic_deal: bool = Field(
        ...,
        description="True if the product is a genuine, high-value deal matching expectations, not a scam or mismatch.",
    )
    is_accessory_or_trap: bool = Field(
        ...,
        description="True if the item is an accessory, cable, tempered glass, skin, case, spare part, or inflated-MRP trap.",
    )
    matched_target_id: str = Field(
        ...,
        description="The ID of the target rule matched (or 'crazy_deal_override' / 'none').",
    )
    extracted_key_specs: str = Field(
        ...,
        description="Concise summary of key extracted specs (e.g., '12GB RAM, 256GB Storage, Snapdragon 8 Gen 3').",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0.",
    )
    model_name: str = Field(
        default="gemini-2.5-flash",
        description="Model that performed the verification.",
    )
    rationale: str = Field(
        ...,
        description="Detailed explanation of the decision.",
    )

    def is_approved_for_checkout(self, min_confidence: float = 0.85) -> bool:
        """Determines if the deal satisfies all safety and authenticity gates."""
        return (
            self.is_authentic_deal is True
            and self.is_accessory_or_trap is False
            and self.confidence_score >= min_confidence
        )


class LLMDealValidator:
    """Verifies deals against natural language specs using Gemini 2.5 Flash & Groq fallback."""

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        confidence_threshold: float = 0.85,
    ):
        self.gemini_api_key = gemini_api_key
        self.groq_api_key = groq_api_key
        self.confidence_threshold = confidence_threshold

    def _build_prompt(
        self,
        product: ParsedProduct,
        matched_target: Optional[TargetItem],
        is_crazy_deal: bool,
    ) -> str:
        """Builds verification prompt."""
        target_spec_desc = (
            f"Target ID: '{matched_target.id}'\nExpected Specs: {matched_target.natural_language_spec}"
            if matched_target
            else "Global Crazy Deal Override (Any genuine high-value consumer electronic/gadget at extreme discount)."
        )

        return f"""You are an elite E-Commerce Deal Verification Agent.
Analyze the following parsed product listing to verify if it is an authentic flash sale or an accessory trap / fake MRP.

[USER SPECIFICATION & EXPECTATIONS]
{target_spec_desc}

[PARSED PRODUCT LISTING]
Platform: {product.platform}
Product ID: {product.product_id}
Title: {product.title}
Current Price: INR {product.current_price_inr}
MRP: INR {product.original_mrp_inr or 'N/A'}
Claimed Discount: {product.discount_percent}%
Seller: {product.seller}
Stock: {'In Stock' if product.in_stock else 'Out of Stock'}
Snippet: {product.raw_text_snippet}

[RULES]
1. Set `is_accessory_or_trap = true` if this is a phone case, tempered glass, cable, adapter, spare part, dummy box, or fake-MRP product pretending to be a main device.
2. Set `is_authentic_deal = true` ONLY if it is the genuine main device matching the user's natural language specification.
3. Return strict JSON matching the schema with confidence_score between 0.0 and 1.0.
"""

    async def verify_deal(
        self,
        product: ParsedProduct,
        matched_target: Optional[TargetItem] = None,
        is_crazy_deal: bool = False,
    ) -> DealVerificationResult:
        """Runs verification through Gemini 2.5 Flash, falling back to Groq."""
        prompt = self._build_prompt(product, matched_target, is_crazy_deal)

        # 1. Try Gemini 2.5 Flash
        if self.gemini_api_key:
            try:
                result = await self._verify_with_gemini(prompt, matched_target)
                if result:
                    return result
            except Exception as e:
                logger.warning("Gemini verification failed (%s); trying Groq fallback", e)

        # 2. Try Groq Llama 3.3 70B Fallback
        if self.groq_api_key:
            try:
                result = await self._verify_with_groq(prompt, matched_target)
                if result:
                    return result
            except Exception as e:
                logger.warning("Groq verification failed (%s)", e)

        # 3. Offline Heuristic Fallback (for development / testing without live keys)
        return self._heuristic_fallback(product, matched_target, is_crazy_deal)

    async def _verify_with_gemini(
        self, prompt: str, matched_target: Optional[TargetItem]
    ) -> Optional[DealVerificationResult]:
        """Calls Gemini API using google-genai SDK."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.gemini_api_key)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DealVerificationResult,
                temperature=0.1,
            ),
        )

        if response and response.text:
            data = json.loads(response.text)
            data["model_name"] = "gemini-2.5-flash"
            return DealVerificationResult(**data)
        return None

    async def _verify_with_groq(
        self, prompt: str, matched_target: Optional[TargetItem]
    ) -> Optional[DealVerificationResult]:
        """Calls Groq Llama 3.3 70B Versatile endpoint with JSON mode."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a deal verification system that outputs strict JSON adhering to schema: {is_authentic_deal: bool, is_accessory_or_trap: bool, matched_target_id: str, extracted_key_specs: str, confidence_score: float, model_name: str, rationale: str}",
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                parsed["model_name"] = "llama-3.3-70b-versatile (groq)"
                return DealVerificationResult(**parsed)
            else:
                logger.error("Groq API error HTTP %d: %s", resp.status_code, resp.text)
        return None

    def _heuristic_fallback(
        self,
        product: ParsedProduct,
        matched_target: Optional[TargetItem],
        is_crazy_deal: bool,
    ) -> DealVerificationResult:
        """Safe heuristic verification for offline testing / mock environments."""
        title_lower = product.title.lower()
        accessories = ["case", "cover", "cable", "tempered glass", "protector", "skin", "adapter"]
        is_accessory = any(acc in title_lower for acc in accessories)

        target_id = matched_target.id if matched_target else ("crazy_deal_override" if is_crazy_deal else "none")
        is_authentic = not is_accessory and product.in_stock and product.current_price_inr > 0

        return DealVerificationResult(
            is_authentic_deal=is_authentic,
            is_accessory_or_trap=is_accessory,
            matched_target_id=target_id,
            extracted_key_specs="Heuristic fallback specs",
            confidence_score=0.90 if is_authentic else 0.10,
            model_name="offline-heuristic",
            rationale="Offline heuristic evaluation without external LLM keys.",
        )
