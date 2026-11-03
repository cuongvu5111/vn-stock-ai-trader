# Ngày tạo: 2026-11-03
# Mục đích: Triển khai các AI Providers (MockAiAnalysisProvider và ConfigurableHttpLlmProvider).
# Lý do:
#   - Đảm bảo kiểm thử deterministic không phụ thuộc mạng ngoài với MockAiAnalysisProvider.
#   - Cho phép kết nối LLM thật qua biến môi trường có timeout rõ ràng và không bao giờ log API key.

import json
from datetime import date
from typing import Any, Dict, List

import httpx

from app.ai.prompting import build_explainable_prompt


class MockAiAnalysisProvider:
    """
    Provider tổng hợp báo cáo giải thích deterministic từ `input_snapshot`.
    Luôn phân biệt rõ [FACT], [INFERENCE] và nêu rõ giới hạn dữ liệu khi thiếu nguồn.
    """

    provider_name: str = "mock"

    def __init__(self, model_name: str = "mock-v1") -> None:
        self.model_name = model_name

    def analyze_signal(
        self,
        symbol: str,
        as_of_date: date,
        input_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        signal_data = input_snapshot.get("signal", {})
        action = signal_data.get("action", "HOLD")
        ref_price = signal_data.get("reference_price", "N/A")
        stop_loss = signal_data.get("stop_loss")
        reasons: List[str] = list(signal_data.get("reasons", []))
        sig_warnings: List[str] = list(signal_data.get("warnings", []))
        sec_warnings: List[str] = list(input_snapshot.get("security_warnings", []))

        fin_metrics = input_snapshot.get("financial_metrics")
        news_list: List[Dict[str, Any]] = list(input_snapshot.get("news_articles", []))

        positive_factors: List[str] = []
        negative_factors: List[str] = []
        risks: List[str] = [
            "[FACT] Tín hiệu kỹ thuật dựa trên dữ liệu lịch sử EOD không đảm bảo lợi nhuận trong tương lai."
        ]
        conflicting_evidence: List[str] = []
        limitations: List[str] = []
        source_references: List[Dict[str, Any]] = [
            {
                "source_id": str(signal_data.get("source_id", "SIGNAL_PRIMARY")),
                "source_type": "SIGNAL",
                "description": f"Tín hiệu {action} từ chiến lược tại ngày {as_of_date.isoformat()}",
                "as_of_date": as_of_date.isoformat(),
            }
        ]

        if action == "BUY":
            for r in reasons:
                positive_factors.append(f"[FACT] {r}")
            positive_factors.append(
                f"[INFERENCE] Động lượng giá và khối lượng tại vùng {ref_price} ủng hộ kịch bản theo xu hướng."
            )
        elif action == "SELL":
            for r in reasons:
                negative_factors.append(f"[FACT] {r}")
            negative_factors.append(
                "[INFERENCE] Cấu trúc kỹ thuật ngắn hạn suy yếu, ưu tiên bảo toàn vốn."
            )
        else:
            conflicting_evidence.append(
                "[FACT] Các điều kiện chiến lược chưa đồng thuận hoàn toàn (trạng thái HOLD)."
            )

        if stop_loss:
            risks.append(f"[FACT] Ngưỡng dừng lỗ kỹ thuật tham chiếu được đặt tại {stop_loss}.")
        else:
            limitations.append("Tín hiệu hiện tại không đính kèm mức dừng lỗ cụ thể (stop_loss = null).")

        if fin_metrics:
            source_references.append(
                {
                    "source_id": str(fin_metrics.get("source_id")),
                    "source_type": "FINANCIAL_METRICS",
                    "description": f"Chỉ số tài chính kỳ {fin_metrics.get('period')}",
                    "as_of_date": as_of_date.isoformat(),
                }
            )
            positive_factors.append(
                f"[FACT] Đã đối chiếu chỉ số tài chính kỳ {fin_metrics.get('period')} (P/E: {fin_metrics.get('pe_ratio')}, ROE: {fin_metrics.get('roe_pct')}%)."
            )
        else:
            limitations.append(
                "MISSING_FINANCIAL_METRICS: Không có dữ liệu báo cáo tài chính cơ bản trong input_snapshot."
            )

        if news_list:
            for n in news_list:
                source_references.append(
                    {
                        "source_id": str(n["source_id"]),
                        "source_type": "NEWS",
                        "description": f"Tin tức từ {n.get('publisher', 'UNKNOWN')}: {n['title']}",
                        "as_of_date": str(n["published_date"]),
                    }
                )
        else:
            limitations.append(
                "MISSING_NEWS_DATA: Không có dữ liệu bài báo/tin tức bên ngoài trong input_snapshot."
            )

        for w in sig_warnings:
            limitations.append(f"SIGNAL_WARNING: {w}")

        for sw in sec_warnings:
            risks.append(f"[SECURITY_WARNING] {sw}")
            limitations.append(
                "UNTRUSTED_CONTENT_SANITIZED: Phát hiện và vô hiệu hóa mẫu văn bản nghi ngờ prompt injection trong tin tức đầu vào."
            )

        summary = (
            f"[FACT] Mã {symbol} ghi nhận tín hiệu {action} tại ngày dữ liệu {as_of_date.isoformat()} "
            f"(giá tham chiếu: {ref_price}). "
            f"[INFERENCE] Báo cáo này chỉ tổng hợp các yếu tố kỹ thuật và nguồn đính kèm để người dùng xem xét trước khi phê duyệt."
        )

        return {
            "summary": summary,
            "positive_factors": positive_factors,
            "negative_factors": negative_factors,
            "risks": risks,
            "conflicting_evidence": conflicting_evidence,
            "source_references": source_references,
            "data_as_of": as_of_date.isoformat(),
            "limitations": limitations,
        }


class ConfigurableHttpLlmProvider:
    """
    Provider kết nối tới dịch vụ LLM qua HTTP JSON API (OpenAI-compatible endpoint).
    Cấu hình hoàn toàn qua biến môi trường, có timeout chặt chẽ và không bao giờ ghi log API key.
    """

    def __init__(
        self,
        provider_name: str,
        model_name: str,
        api_key: str,
        endpoint_url: str = "https://api.openai.com/v1/chat/completions",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self._api_key = api_key
        self.endpoint_url = endpoint_url
        self.timeout_seconds = timeout_seconds

    def analyze_signal(
        self,
        symbol: str,
        as_of_date: date,
        input_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("Thiếu cấu hình LLM_API_KEY / AI_API_KEY cho LLM provider.")

        prompt_bundle = build_explainable_prompt(input_snapshot)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {
            "model": self.model_name,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": prompt_bundle["system_prompt"]},
                {"role": "user", "content": prompt_bundle["user_prompt"]},
            ],
        }
        if any(k in self.model_name.lower() for k in ("gemma", "qwen", "deepseek")):
            body["chat_template_kwargs"] = {"enable_thinking": False}

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(self.endpoint_url, headers=headers, json=body)
            if response.status_code == 400 and "chat_template_kwargs" in body:
                body.pop("chat_template_kwargs", None)
                response = client.post(self.endpoint_url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            raw_content = str(data["choices"][0]["message"]["content"]).strip()
            if raw_content.startswith("```"):
                lines = raw_content.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                raw_content = "\n".join(lines).strip()
            return json.loads(raw_content)
