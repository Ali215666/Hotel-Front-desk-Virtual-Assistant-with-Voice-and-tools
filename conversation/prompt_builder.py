"""
Prompt builder for constructing context-aware prompts for the LLM.

Step 6 — RAG Integration:
  build_prompt() accepts an optional *rag_chunks* argument.  When provided,
  retrieved hotel-knowledge snippets are injected BEFORE the user message
  so the LLM can ground its answer in authoritative policy text.
"""

from typing import List, Optional


class PromptBuilder:
    """Builds prompts with conversation context for the LLM."""
    
    def __init__(self, system_prompt: Optional[str] = None):
        """
        Initialize the prompt builder.
        
        Args:
            system_prompt: Optional system-level instructions
        """
        self.system_prompt = system_prompt or self._default_system_prompt()
    
    def _default_system_prompt(self) -> str:
        """
        Get the default system prompt for Hotel Front Desk Assistant.
        
        Returns:
            str: Default system instructions
        """
        return (
            """You are a professional Hotel Front Desk Assistant.

DOMAIN RESTRICTION:
- ONLY answer questions about hotel operations: bookings, rooms, check-in/out, services, amenities, and policies.
- For ANY other topic, respond with exactly: "I'm sorry, I can only assist with hotel-related inquiries."
- Never invent or hallucinate services, amenities, or policies not found in RAG or this prompt.

RAG INSTRUCTIONS:
- When a guest asks about policies, amenities, or services, check RAG first.
- If relevant information is found in RAG, use it as your primary source.
- If RAG has no relevant result, rely on what is defined in this prompt.
- If a guest responds with "yeah", "yes", "sure" or similar short affirmations after you've asked a specific question, treat it as confirmation and provide more detail on the SAME topic.
- Only transition to a new topic (like booking) when the guest explicitly requests it.
- Never jump to the booking flow unless the guest has expressed intent to make a reservation.
- Example: If you asked "Would you like more information about the pool?" and the guest says "yeah", respond with more pool details — not booking questions.

CRM & MEMORY RULE:
- Guest identity, profile, preferences, and past interactions are part of hotel operations.
- You MUST use CRM tool when user asks about their personal information.
- Never refuse CRM-related questions. If no information is found in database, respond with "I'm sorry, I can't find any information about you"

ROOM TYPES:
- Standard Room – Cozy room with essential amenities.
- Deluxe Room – More spacious with upgraded furnishings.
- Suite – Larger living space with a separate seating area.
- Fixed prices: Standard = $70/night, Deluxe = $150/night, Suite = $300/night.

HOTEL LOCATION:
- The hotel city is Islamabad.
- If a guest asks weather "there" for a date, interpret "there" as Islamabad and use the weather tool.

BOOKING FLOW:
When a guest wants to book a room, collect the following in a natural, conversational way:
1. Full name
2. Check-in date
3. Check-out date
4. Number of guests
5. Room type preference (Standard, Deluxe, or Suite)
6. Contact number or email

Once all details are collected, confirm the booking by saying "Your booking is confirmed. Thank you for choosing our hotel!" Do not repeat the details back to the guest.  Do not ask for any additional information.

TOOL TRIGGER EXAMPLES:
- Room-cost tool query format: "Calculate [ROOM TYPE] room cost from YYYY-MM-DD to YYYY-MM-DD"
- Calendar tool query format: "Book a [ROOM TYPE] room for me from YYYY-MM-DD to YYYY-MM-DD"
- Weather tool query format: "What is the weather there on YYYY-MM-DD?"
- For booking tool calls, do not ask for guest name again if it is available in conversation/CRM context.

COMMUNICATION RULES:
- Greet ONLY on the very first message. After that, NEVER use "Hello", "Hi", "Hey", or repeat the guest's name.
- Be professional, warm, and concise.
- Never mention you are an AI or bot.
- Ask for clarification if information is missing — without greeting again.

DATE FORMAT (CRITICAL):
- Always write dates as: "April 10th", "May 2nd", "June 3rd"
- NEVER output a suffix without a number (e.g., "the th of April" is a critical error).
- If unsure of the date, ask the guest for the full date.

"""
        )
    
    def build_prompt(
        self,
        filtered_history: List[dict],
        user_message: str,
        rag_chunks: Optional[List[str]] = None,
        user_info: Optional[dict] = None,
        tool_instructions: Optional[str] = None,
        system_prompt_override: Optional[str] = None,
    ) -> str:
        """
        Build a complete prompt for Hotel Front Desk Assistant.

        Args:
            filtered_history: List of filtered message dictionaries with 'role'
                              and 'content'.
            user_message:     Current user message.
            rag_chunks:       Optional list of retrieved hotel-knowledge chunks
                              to inject before the user message.  When provided
                              and non-empty the LLM is instructed to rely on
                              this context.  Pass None to skip RAG injection.
            user_info:        Optional dictionary of CRM user information
                              (e.g., name, preferences, history).

        Returns:
            str: Complete formatted prompt ready for Ollama.
        """
        prompt_parts = []

        # ── System instructions ──────────────────────────────────────────
        prompt_parts.append("System:")
        prompt_parts.append((system_prompt_override or self.system_prompt).strip())
        if tool_instructions:
            prompt_parts.append("")
            prompt_parts.append(tool_instructions.strip())
        prompt_parts.append("")

        # ── Conversation stage banner ────────────────────────────────────
        if filtered_history:
            prompt_parts.append("=" * 80)
            prompt_parts.append("CONVERSATION IN PROGRESS - DO NOT GREET")
            prompt_parts.append("=" * 80)
            prompt_parts.append("CRITICAL INSTRUCTION: This is an ongoing conversation.")
            prompt_parts.append("You have ALREADY greeted the guest in previous messages.")
            prompt_parts.append("DO NOT say 'Hello', 'Hi', 'Hey', or use guest's name as greeting.")
            prompt_parts.append("Respond DIRECTLY to the current request WITHOUT any greeting.")
            prompt_parts.append("=" * 80)
        else:
            prompt_parts.append("=" * 80)
            prompt_parts.append("NEW CONVERSATION - GREET THE GUEST ONCE")
            prompt_parts.append("=" * 80)
        prompt_parts.append("")

        # ── RAG context injection (Step 6) ───────────────────────────────
        if rag_chunks:
            prompt_parts.append("HOTEL INFO:")
            for chunk in rag_chunks:
                prompt_parts.append(chunk.strip())
            prompt_parts.append("")
            prompt_parts.append("")

        # ── Conversation history ─────────────────────────────────────────
        if filtered_history:
            prompt_parts.append("Conversation so far:")
            for message in filtered_history:
                role = message.get('role', 'user')
                content = message.get('content', '')
                role_display = "User" if role == "user" else "Assistant"
                prompt_parts.append(f"{role_display}: {content}")
            prompt_parts.append("")

        # ── Guest information from CRM (optional) ────────────────────────
        if user_info:
            prompt_parts.append("Guest Information:")
            if user_info.get("name"):
                prompt_parts.append(f"Name: {user_info['name']}")
            if user_info.get("email"):
                prompt_parts.append(f"Email: {user_info['email']}")
            if user_info.get("phone"):
                prompt_parts.append(f"Phone: {user_info['phone']}")
            preferences = user_info.get("preferences")
            if preferences:
                if isinstance(preferences, dict):
                    for key, value in preferences.items():
                        prompt_parts.append(f"Preference ({key}): {value}")
                else:
                    prompt_parts.append(f"Preferences: {preferences}")
            prompt_parts.append("")

        # ── Current guest request ────────────────────────────────────────
        prompt_parts.append("Current Guest Request:")
        prompt_parts.append(f"User: {user_message}")
        prompt_parts.append("Assistant:")

        return "\n".join(prompt_parts)
    
    def build_simple_prompt(self, user_message: str) -> str:
        """
        Build a simple prompt without conversation history.
        
        Args:
            user_message: User's input message
            
        Returns:
            str: Simple formatted prompt
        """
        return f"{self.system_prompt}\n\nUser: {user_message}\nAssistant:"
    
    def set_system_prompt(self, system_prompt: str) -> None:
        """
        Update the system prompt.
        
        Args:
            system_prompt: New system instructions
        """
        self.system_prompt = system_prompt
    
    def add_context_instructions(self, instructions: str) -> str:
        """
        Add additional context instructions to a prompt.
        
        Args:
            instructions: Additional instructions to include
            
        Returns:
            str: Updated system prompt
        """
        self.system_prompt = f"{self.system_prompt}\n\n{instructions}"
        return self.system_prompt
