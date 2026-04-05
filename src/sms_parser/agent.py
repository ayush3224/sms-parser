"""Claude-powered SMS spend agent with tool use."""

import json
from datetime import date, datetime, timedelta
from typing import List, Optional

import anthropic
import pytz

from .models import SMSMessage, Transaction, TransactionType

IST = pytz.timezone("Asia/Kolkata")

MODEL = "claude-opus-4-6"

SYSTEM_PROMPT = """You are a personal finance assistant that analyses business SMS messages \
from Indian banks and payment apps. You help users understand their spending patterns.

Today's date (IST): {today}

You have access to the following tools to query the user's SMS transaction data:
- get_transactions: Filter transactions by date, type, amount range, merchant, bank, or payment mode
- search_sms: Full-text search across all SMS messages
- get_spend_summary: Compute a numeric spend summary for a specific date

When answering queries:
- Use the tools to fetch relevant data before drawing conclusions.
- Present amounts in Indian Rupee format (e.g., ₹1,234.56).
- Be concise and insightful — highlight the largest spends, common merchants, etc.
- If you cannot find relevant data, say so clearly.
"""

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_transactions",
        "description": (
            "Retrieve transactions filtered by various criteria. "
            "All parameters are optional — omit to include all records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format (inclusive).",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format (inclusive).",
                },
                "transaction_type": {
                    "type": "string",
                    "enum": ["debit", "credit", "unknown"],
                    "description": "Filter by transaction type.",
                },
                "min_amount": {
                    "type": "number",
                    "description": "Minimum transaction amount in INR.",
                },
                "max_amount": {
                    "type": "number",
                    "description": "Maximum transaction amount in INR.",
                },
                "merchant": {
                    "type": "string",
                    "description": "Case-insensitive substring match on merchant name.",
                },
                "bank": {
                    "type": "string",
                    "description": "Case-insensitive substring match on bank name.",
                },
                "payment_mode": {
                    "type": "string",
                    "description": "Case-insensitive substring match on payment mode (e.g. UPI, ATM, NEFT).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 50).",
                },
            },
        },
    },
    {
        "name": "get_spend_summary",
        "description": "Compute a numeric spend/credit summary for a specific date or date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Defaults to start_date if not provided.",
                },
            },
            "required": ["start_date"],
        },
    },
    {
        "name": "search_sms",
        "description": "Full-text search across raw SMS bodies. Returns matching SMS messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term to look for in SMS text (case-insensitive).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 20).",
                },
            },
            "required": ["query"],
        },
    },
]


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class SMSSpendAgent:
    def __init__(
        self,
        sms_messages: List[SMSMessage],
        transactions: List[Transaction],
        api_key: str,
    ):
        self._sms = sms_messages
        self._transactions = transactions
        self._client = anthropic.Anthropic(api_key=api_key)
        self._conversation: List[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_daily_spend_summary(self, for_date: Optional[date] = None) -> str:
        """Generate a natural-language spend summary for the given date (defaults to yesterday)."""
        if for_date is None:
            for_date = (datetime.now(tz=IST) - timedelta(days=1)).date()

        date_str = for_date.isoformat()
        summary_data = self._compute_spend_summary(date_str, date_str)

        if summary_data["transaction_count"] == 0:
            return f"No transactions found for {date_str}."

        prompt = (
            f"Generate a concise spend summary for {date_str} based on this data:\n"
            f"{json.dumps(summary_data, indent=2)}\n\n"
            "Format it as a brief daily report with total spend, top merchants, "
            "and any notable credits. Use ₹ for amounts."
        )

        response = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT.format(today=datetime.now(tz=IST).date().isoformat()),
            messages=[{"role": "user", "content": prompt}],
        )
        return self._extract_text(response)

    def answer_query(self, user_query: str) -> str:
        """Answer a natural language question about the SMS/transactions using an agentic loop."""
        self._conversation.append({"role": "user", "content": user_query})

        while True:
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT.format(today=datetime.now(tz=IST).date().isoformat()),
                tools=TOOLS,
                messages=self._conversation,
            )

            # Always append assistant response to history
            self._conversation.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                return self._extract_text(response)

            if response.stop_reason != "tool_use":
                return self._extract_text(response)

            # Execute tool calls and feed results back
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

            self._conversation.append({"role": "user", "content": tool_results})

    def reset_conversation(self):
        """Clear conversation history."""
        self._conversation = []

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, inputs: dict) -> dict:
        if name == "get_transactions":
            return self._tool_get_transactions(inputs)
        elif name == "get_spend_summary":
            return self._tool_get_spend_summary(inputs)
        elif name == "search_sms":
            return self._tool_search_sms(inputs)
        else:
            return {"error": f"Unknown tool: {name}"}

    def _tool_get_transactions(self, inputs: dict) -> dict:
        txns = list(self._transactions)

        start_date = inputs.get("start_date")
        end_date = inputs.get("end_date")
        if start_date:
            txns = [t for t in txns if t.timestamp.date().isoformat() >= start_date]
        if end_date:
            txns = [t for t in txns if t.timestamp.date().isoformat() <= end_date]

        txn_type = inputs.get("transaction_type")
        if txn_type:
            txns = [t for t in txns if t.transaction_type.value == txn_type]

        min_amount = inputs.get("min_amount")
        if min_amount is not None:
            txns = [t for t in txns if t.amount >= min_amount]

        max_amount = inputs.get("max_amount")
        if max_amount is not None:
            txns = [t for t in txns if t.amount <= max_amount]

        merchant = inputs.get("merchant")
        if merchant:
            merchant_lower = merchant.lower()
            txns = [t for t in txns if t.merchant and merchant_lower in t.merchant.lower()]

        bank = inputs.get("bank")
        if bank:
            bank_lower = bank.lower()
            txns = [t for t in txns if t.bank and bank_lower in t.bank.lower()]

        payment_mode = inputs.get("payment_mode")
        if payment_mode:
            pm_lower = payment_mode.lower()
            txns = [t for t in txns if t.payment_mode and pm_lower in t.payment_mode.lower()]

        limit = inputs.get("limit", 50)
        txns = sorted(txns, key=lambda t: t.timestamp, reverse=True)[:limit]

        return {
            "count": len(txns),
            "transactions": [t.to_dict() for t in txns],
        }

    def _tool_get_spend_summary(self, inputs: dict) -> dict:
        start_date = inputs["start_date"]
        end_date = inputs.get("end_date", start_date)
        return self._compute_spend_summary(start_date, end_date)

    def _tool_search_sms(self, inputs: dict) -> dict:
        query = inputs["query"].lower()
        limit = inputs.get("limit", 20)

        matches = [
            sms.to_dict()
            for sms in self._sms
            if query in sms.body.lower() or query in sms.sender.lower()
        ][:limit]

        return {"count": len(matches), "messages": matches}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_spend_summary(self, start_date: str, end_date: str) -> dict:
        txns = [
            t for t in self._transactions
            if start_date <= t.timestamp.date().isoformat() <= end_date
        ]

        debits = [t for t in txns if t.transaction_type == TransactionType.DEBIT]
        credits = [t for t in txns if t.transaction_type == TransactionType.CREDIT]

        total_debit = sum(t.amount for t in debits)
        total_credit = sum(t.amount for t in credits)

        # Top merchants by spend
        merchant_totals: dict = {}
        for t in debits:
            key = t.merchant or "Unknown"
            merchant_totals[key] = merchant_totals.get(key, 0) + t.amount
        top_merchants = sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:5]

        # Payment mode breakdown
        mode_totals: dict = {}
        for t in debits:
            key = t.payment_mode or "Other"
            mode_totals[key] = mode_totals.get(key, 0) + t.amount

        return {
            "start_date": start_date,
            "end_date": end_date,
            "transaction_count": len(txns),
            "debit_count": len(debits),
            "credit_count": len(credits),
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "net": round(total_credit - total_debit, 2),
            "top_merchants": [{"merchant": m, "amount": round(a, 2)} for m, a in top_merchants],
            "payment_mode_breakdown": {k: round(v, 2) for k, v in mode_totals.items()},
            "largest_transaction": max(
                (t.to_dict() for t in txns), key=lambda x: x["amount"], default=None
            ),
        }

    @staticmethod
    def _extract_text(response) -> str:
        parts = [block.text for block in response.content if hasattr(block, "text")]
        return "\n".join(parts).strip() or "(No text response)"
