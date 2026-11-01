"""Unit tests for Cloud LLM Verification engine and schema outputs."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.config_loader import TargetItem
from src.intelligence.llm_validator import DealVerificationResult, LLMDealValidator
from src.scraper.product_fetcher import ParsedProduct


@pytest.fixture
def sample_product():
    return ParsedProduct(
        platform="amazon",
        product_id="B0CQPLJPTM",
        title="OnePlus 12 (12GB RAM, 256GB Storage)",
        current_price_inr=19999.0,
        original_mrp_inr=64999.0,
        discount_percent=69.2,
        in_stock=True,
        seller="Appario Retail",
        rating=4.5,
        canonical_url="https://amazon.in/dp/B0CQPLJPTM",
        raw_text_snippet="OnePlus 12 12GB RAM, 256GB Storage, Snapdragon 8 Gen 3",
    )


@pytest.fixture
def sample_target():
    return TargetItem(
        id="flagship_smartphone",
        name="Flagship Smartphone",
        natural_language_spec="Smartphone with >=8GB RAM, modern 5G processor, AMOLED display.",
        max_price_inr=25000.0,
        min_discount_percent=30.0,
        negative_keywords=["case", "cover", "cable"],
    )


def test_deal_verification_result_approval_logic():
    # 1. Fully authentic deal with high confidence -> Approved
    res_valid = DealVerificationResult(
        is_authentic_deal=True,
        is_accessory_or_trap=False,
        matched_target_id="flagship_smartphone",
        extracted_key_specs="12GB RAM, 256GB Storage, Snapdragon 8 Gen 3",
        confidence_score=0.95,
        model_name="gemini-2.5-flash",
        rationale="Matches flagship specs and genuine phone.",
    )
    assert res_valid.is_approved_for_checkout(min_confidence=0.85) is True

    # 2. Accessory or trap -> Disapproved
    res_trap = DealVerificationResult(
        is_authentic_deal=True,
        is_accessory_or_trap=True,
        matched_target_id="flagship_smartphone",
        extracted_key_specs="Tempered glass screen protector",
        confidence_score=0.92,
        model_name="gemini-2.5-flash",
        rationale="Item is a screen protector accessory.",
    )
    assert res_trap.is_approved_for_checkout(min_confidence=0.85) is False

    # 3. Authentic but low confidence (< 0.85) -> Disapproved
    res_low_conf = DealVerificationResult(
        is_authentic_deal=True,
        is_accessory_or_trap=False,
        matched_target_id="flagship_smartphone",
        extracted_key_specs="Unknown brand phone",
        confidence_score=0.72,
        model_name="gemini-2.5-flash",
        rationale="Cannot confirm processor specs.",
    )
    assert res_low_conf.is_approved_for_checkout(min_confidence=0.85) is False


async def test_offline_heuristic_verification(sample_product, sample_target):
    validator = LLMDealValidator(gemini_api_key=None, groq_api_key=None)
    result = await validator.verify_deal(sample_product, sample_target)

    assert result.is_authentic_deal is True
    assert result.is_accessory_or_trap is False
    assert result.confidence_score >= 0.85
    assert result.is_approved_for_checkout() is True


async def test_groq_fallback_mocked(sample_product, sample_target):
    validator = LLMDealValidator(
        gemini_api_key=None,
        groq_api_key="test_groq_key",
    )

    mock_groq_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "is_authentic_deal": True,
                        "is_accessory_or_trap": False,
                        "matched_target_id": "flagship_smartphone",
                        "extracted_key_specs": "12GB RAM, 256GB Storage, SD 8 Gen 3",
                        "confidence_score": 0.96,
                        "model_name": "llama-3.3-70b-versatile",
                        "rationale": "High end smartphone matching all specs.",
                    })
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_groq_response
        mock_post.return_value = mock_resp

        result = await validator.verify_deal(sample_product, sample_target)

        assert result.is_authentic_deal is True
        assert result.is_accessory_or_trap is False
        assert result.confidence_score == 0.96
        assert "groq" in result.model_name
        assert result.is_approved_for_checkout() is True
