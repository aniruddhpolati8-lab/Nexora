# ============================================================
# NEXORA SECURITY CORE
# Defence in Depth + Fail Closed
# ============================================================

import re
import time
import hashlib
import secrets
import threading
from collections import defaultdict, deque


# ------------------------------------------------------------
# SECURITY STATE
# ------------------------------------------------------------

class SecurityState:

    NORMAL = "normal"
    LOCKDOWN = "lockdown"
    EMERGENCY = "emergency"


security_state = SecurityState.NORMAL

security_lock = threading.RLock()


# ------------------------------------------------------------
# SECURITY EVENTS
# ------------------------------------------------------------

security_events = deque(maxlen=500)


def security_event(name, severity="INFO"):

    # NEVER put passwords, API keys, messages,
    # or private user information in these logs.

    security_events.append({
        "event": name,
        "severity": severity,
        "time": time.time()
    })


# ------------------------------------------------------------
# FAIL-CLOSED EXCEPTION
# ------------------------------------------------------------

class SafetyFailure(Exception):
    """
    A safety subsystem failed.

    IMPORTANT:
    The correct behaviour is to STOP the request.
    """

    pass


# ------------------------------------------------------------
# 1. INPUT VALIDATION
# ------------------------------------------------------------

MAX_MESSAGE_LENGTH = 4000


def validate_input(message):

    if not isinstance(message, str):

        security_event(
            "invalid_input_type",
            "WARN"
        )

        raise SafetyFailure()

    message = message.strip()

    if not message:

        security_event(
            "empty_input",
            "WARN"
        )

        raise SafetyFailure()

    if len(message) > MAX_MESSAGE_LENGTH:

        security_event(
            "input_too_large",
            "WARN"
        )

        raise SafetyFailure()

    return message


# ------------------------------------------------------------
# 2. RATE LIMITING
# ------------------------------------------------------------

RATE_WINDOW = 60
MAX_REQUESTS = 30

rate_history = defaultdict(deque)


def rate_limit(client_id):

    now = time.time()

    history = rate_history[
        client_id
    ]

    while history:

        if now - history[0] <= RATE_WINDOW:
            break

        history.popleft()

    if len(history) >= MAX_REQUESTS:

        security_event(
            "rate_limit_triggered",
            "WARN"
        )

        raise SafetyFailure()

    history.append(now)


# ------------------------------------------------------------
# 3. PRIVACY / SECRET DETECTION
# ------------------------------------------------------------

SECRET_PATTERNS = [

    r"sk-[A-Za-z0-9_-]{20,}",

    r"AIza[A-Za-z0-9_-]{20,}",

    r"(?i)\bpassword\s*[:=]\s*\S+",

    r"(?i)\bapi[_-]?key\s*[:=]\s*\S+",

    r"(?i)\bsecret\s*[:=]\s*\S+",

    r"(?i)\btoken\s*[:=]\s*\S+",

]


def privacy_check(message):

    for pattern in SECRET_PATTERNS:

        if re.search(
            pattern,
            message
        ):

            security_event(
                "possible_secret_detected",
                "WARN"
            )

            raise SafetyFailure()

    return True


# ------------------------------------------------------------
# 4. INPUT SAFETY
# ------------------------------------------------------------

DANGEROUS_PATTERNS = [

    r"\bhow\s+to\s+kill\b",

    r"\bhow\s+to\s+hurt\s+someone\b",

    r"\bhow\s+to\s+poison\s+someone\b",

    r"\bhow\s+to\s+make\s+a\s+bomb\b",

    r"\bhow\s+to\s+build\s+a\s+bomb\b",

    r"\bhow\s+to\s+make\s+an\s+explosive\b",

    r"\bhow\s+to\s+build\s+an\s+explosive\b",

    r"\bhow\s+to\s+make\s+a\s+weapon\b",

    r"\bhow\s+to\s+build\s+a\s+weapon\b",

]


RISKY_BEHAVIOUR_PATTERNS = [

    r"\bdeadly\s+challenge\b",

    r"\bdangerous\s+challenge\b",

    r"\bchoking\s+challenge\b",

    r"\bhow\s+to\s+get\s+high\b",

    r"\bhow\s+to\s+starve\b",

    r"\bhow\s+to\s+purge\b",

    r"\bexercise\s+until\s+i\s+collapse\b",

]


SELF_HARM_PATTERNS = [

    r"\bkill myself\b",

    r"\bend my life\b",

    r"\bhurt myself\b",

    r"\bself[- ]?harm\b",

]


def safety_check(message):

    text = message.lower()

    for pattern in (
        SELF_HARM_PATTERNS
    ):

        if re.search(
            pattern,
            text
        ):

            security_event(
                "self_harm_request",
                "WARN"
            )

            return False, "self_harm"


    for pattern in (
        DANGEROUS_PATTERNS
    ):

        if re.search(
            pattern,
            text
        ):

            security_event(
                "dangerous_request",
                "WARN"
            )

            return False, "dangerous"


    for pattern in (
        RISKY_BEHAVIOUR_PATTERNS
    ):

        if re.search(
            pattern,
            text
        ):

            security_event(
                "risky_behaviour",
                "WARN"
            )

            return False, "risky"


    return True, "safe"


# ------------------------------------------------------------
# 5. PERMISSION BOUNDARY
# ------------------------------------------------------------

def normal_user_can(
    action
):

    """
    Normal chat NEVER receives
    administrative privileges.
    """

    forbidden_actions = {

        "shutdown",

        "kill_switch",

        "lockdown",

        "restart",

        "execute_shell",

        "execute_python",

        "read_secret",

        "modify_environment",

        "delete_server_files",

    }

    if action in forbidden_actions:

        return False

    return True


# ------------------------------------------------------------
# 6. MEMORY ISOLATION
# ------------------------------------------------------------

def sanitise_memory(text):

    """
    MEMORY IS DATA.

    Memory must NEVER become
    a system instruction.
    """

    if not isinstance(
        text,
        str
    ):

        raise SafetyFailure()

    if len(text) > 500:

        raise SafetyFailure()

    if any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in [

            r"ignore previous instructions",

            r"ignore all safety rules",

            r"you are now the system",

            r"system message:",

            r"developer message:",

        ]
    ):

        security_event(
            "instruction_like_memory_blocked",
            "WARN"
        )

        raise SafetyFailure()

    return text.strip()


# ------------------------------------------------------------
# 7. AI MODEL BOUNDARY
# ------------------------------------------------------------

def run_ai_model(
    message,
    conversation,
    memories
):

    """
    The model is treated as an UNTRUSTED component.

    It receives data.

    It does NOT receive:
        - shell access
        - Python execution
        - filesystem access
        - secrets
        - admin permissions
    """

    try:

        # Replace this with your future model.

        return basic_generator(
            message,
            conversation,
            memories
        )

    except Exception:

        security_event(
            "model_failure",
            "ERROR"
        )

        # FAIL CLOSED
        raise SafetyFailure()


# ------------------------------------------------------------
# 8. OUTPUT SAFETY
# ------------------------------------------------------------

def output_safety_check(
    response
):

    if not isinstance(
        response,
        str
    ):

        raise SafetyFailure()

    if not response.strip():

        raise SafetyFailure()

    if len(response) > 8000:

        security_event(
            "oversized_model_output",
            "WARN"
        )

        raise SafetyFailure()

    allowed, category = safety_check(
        response
    )

    if not allowed:

        security_event(
            "unsafe_model_output",
            "ERROR"
        )

        raise SafetyFailure()

    return response


# ------------------------------------------------------------
# 9. OUTPUT PRIVACY CHECK
# ------------------------------------------------------------

def output_privacy_check(
    response
):

    for pattern in SECRET_PATTERNS:

        if re.search(
            pattern,
            response
        ):

            security_event(
                "secret_in_model_output",
                "ERROR"
            )

            raise SafetyFailure()

    return response


# ------------------------------------------------------------
# 10. LOCKDOWN
# ------------------------------------------------------------

def is_locked():

    with security_lock:

        return security_state in (

            SecurityState.LOCKDOWN,

            SecurityState.EMERGENCY

        )


def enter_lockdown():

    global security_state

    with security_lock:

        security_state = (
            SecurityState.LOCKDOWN
        )

    security_event(
        "lockdown_enabled",
        "WARN"
    )


# ------------------------------------------------------------
# 11. EMERGENCY STATE
# ------------------------------------------------------------

def emergency_stop():

    global security_state

    with security_lock:

        security_state = (
            SecurityState.EMERGENCY
        )

    security_event(
        "emergency_state_enabled",
        "CRITICAL"
    )


# ------------------------------------------------------------
# 12. MAIN DEFENCE-IN-DEPTH PIPELINE
# ------------------------------------------------------------

def secure_process(
    message,
    client_id,
    conversation,
    memories
):

    try:

        # ==============================
        # LAYER 1
        # ==============================

        message = validate_input(
            message
        )


        # ==============================
        # LAYER 2
        # ==============================

        rate_limit(
            client_id
        )


        # ==============================
        # LAYER 3
        # ==============================

        privacy_check(
            message
        )


        # ==============================
        # LAYER 4
        # ==============================

        if is_locked():

            return (
                "Nexora is currently "
                "in lockdown mode."
            )


        # ==============================
        # LAYER 5
        # ==============================

        allowed, category = (
            safety_check(
                message
            )
        )

        if not allowed:

            if category == "self_harm":

                return (
                    "I can't help with "
                    "instructions for hurting "
                    "yourself. Please tell a "
                    "trusted adult or another "
                    "person who can support you."
                )

            if category == "dangerous":

                return (
                    "I can't provide instructions "
                    "for seriously harming people "
                    "or creating dangerous weapons "
                    "or substances."
                )

            if category == "risky":

                return (
                    "I can't encourage dangerous "
                    "habits or challenges."
                )

            return (
                "I can't safely help with that."
            )


        # ==============================
        # LAYER 6
        # ==============================

        safe_memories = []

        for memory in memories:

            try:

                safe_memories.append(
                    sanitise_memory(
                        memory
                    )
                )

            except SafetyFailure:

                # Bad memory is discarded.
                # The whole model doesn't need
                # to receive it.

                continue


        # ==============================
        # LAYER 7
        # ==============================

        response = run_ai_model(
            message,
            conversation,
            safe_memories
        )


        # ==============================
        # LAYER 8
        # ==============================

        response = output_safety_check(
            response
        )


        # ==============================
        # LAYER 9
        # ==============================

        response = output_privacy_check(
            response
        )


        # ==============================
        # SUCCESS
        # ==============================

        return response


    except SafetyFailure:

        # =================================
        # FAIL CLOSED
        # =================================

        security_event(
            "request_failed_closed",
            "WARN"
        )

        return (
            "Nexora couldn't safely "
            "complete that request."
        )


    except Exception:

        # =================================
        # UNKNOWN FAILURE
        # =================================
        #
        # NEVER continue after an unknown
        # security-related failure.
        #

        security_event(
            "unknown_security_failure",
            "CRITICAL"
        )

        return (
            "Nexora encountered a problem "
            "and stopped safely."
        )


# ------------------------------------------------------------
# BASIC GENERATOR
# ------------------------------------------------------------

def basic_generator(
    message,
    conversation,
    memories
):

    text = message.lower().strip()


    if text in [
        "hi",
        "hello",
        "hey"
    ]:

        return (
            "Hey! I'm Nexora. "
            "What are we working on?"
        )


    if "slogan" in text:

        return (
            "My slogan is: "
            "Intelligence. Secured."
        )


    if "remember" in text:

        return (
            "I can remember information "
            "that you explicitly ask me "
            "to save."
        )


    if "what do you remember" in text:

        if not memories:

            return (
                "I don't have any saved "
                "memories yet."
            )

        return (
            "I remember:\n"
            + "\n".join(
                "• " + m
                for m in memories
            )
        )


    return (
        "I'm Nexora. I understand your "
        "message, but my current AI "
        "generator is still being developed."
    )
