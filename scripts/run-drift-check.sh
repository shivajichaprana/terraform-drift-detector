#\!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# run-drift-check.sh — CI wrapper for Terraform drift detection
#
# Handles Terraform initialization, workspace selection, and detector
# invocation. Designed for GitHub Actions but works in any CI system.
#
# Usage:
#   ./scripts/run-drift-check.sh --config config.yaml [options]
#
# Options:
#   --config FILE          Path to drift detection config (required)
#   --output-format FMT    Output format: console, json, markdown (default: console)
#   --output-file FILE     Write results to file instead of stdout
#   --exit-code            Exit with code 2 if drift is detected
#   --notify CHANNEL       Send notification (slack, email)
#   --terraform-version    Display Terraform version and exit
#   --help                 Show this help message
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# ── Defaults ──────────────────────────────────────────────────────────
CONFIG_FILE=""
OUTPUT_FORMAT="console"
OUTPUT_FILE=""
EXIT_CODE_FLAG=false
NOTIFY_CHANNELS=()

# ── Functions ─────────────────────────────────────────────────────────

usage() {
    sed -n '/^# Usage:/,/^# ─/p' "$0" | head -n -1 | sed 's/^# //'
    exit 0
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $*"
}

check_prerequisites() {
    local missing=()

    if \! command -v terraform &>/dev/null; then
        missing+=("terraform")
    fi

    if \! command -v python3 &>/dev/null && \! command -v python &>/dev/null; then
        missing+=("python3")
    fi

    if \! command -v drift-detector &>/dev/null; then
        # Fall back to module invocation
        local python_cmd
        python_cmd=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
        if \! "$python_cmd" -m detector --version &>/dev/null 2>&1; then
            missing+=("drift-detector (pip install -e .)")
        fi
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Missing prerequisites: ${missing[*]}"
        log_error "Install them before running drift detection."
        exit 1
    fi
}

get_python_cmd() {
    if command -v python3 &>/dev/null; then
        echo "python3"
    elif command -v python &>/dev/null; then
        echo "python"
    else
        log_error "Python not found"
        exit 1
    fi
}

get_detector_cmd() {
    if command -v drift-detector &>/dev/null; then
        echo "drift-detector"
    else
        echo "$(get_python_cmd) -m detector"
    fi
}

validate_config() {
    local config_file="$1"

    if [ \! -f "$config_file" ]; then
        log_error "Configuration file not found: $config_file"
        exit 1
    fi

    # Basic YAML syntax check
    local python_cmd
    python_cmd=$(get_python_cmd)
    if \! "$python_cmd" -c "import yaml; yaml.safe_load(open('$config_file'))" 2>/dev/null; then
        log_error "Invalid YAML in configuration file: $config_file"
        exit 1
    fi

    log_info "Configuration validated: $config_file"
}

show_terraform_info() {
    log_info "Terraform version:"
    terraform version 2>/dev/null || log_warn "Terraform not available"
    echo ""
}

run_detection() {
    local detector_cmd
    detector_cmd=$(get_detector_cmd)

    local cmd_args=("detect" "--config" "$CONFIG_FILE")

    if [ -n "$OUTPUT_FORMAT" ]; then
        cmd_args+=("--output-format" "$OUTPUT_FORMAT")
    fi

    if [ -n "$OUTPUT_FILE" ]; then
        cmd_args+=("--output-file" "$OUTPUT_FILE")
    fi

    if [ "$EXIT_CODE_FLAG" = true ]; then
        cmd_args+=("--exit-code")
    fi

    for channel in "${NOTIFY_CHANNELS[@]}"; do
        cmd_args+=("--notify" "$channel")
    done

    cmd_args+=("-v")

    log_info "Running: $detector_cmd ${cmd_args[*]}"
    echo ""

    # Run detector and capture exit code
    local exit_code=0
    $detector_cmd "${cmd_args[@]}" || exit_code=$?

    return $exit_code
}

# ── Argument Parsing ──────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --output-format)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        --output-file)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        --exit-code)
            EXIT_CODE_FLAG=true
            shift
            ;;
        --notify)
            NOTIFY_CHANNELS+=("$2")
            shift 2
            ;;
        --terraform-version)
            terraform version
            exit 0
            ;;
        --help|-h)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# ── Main ──────────────────────────────────────────────────────────────

if [ -z "$CONFIG_FILE" ]; then
    log_error "--config is required"
    usage
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Terraform Drift Detector — CI Runner"
echo "════════════════════════════════════════════════════════════"
echo ""

log_info "Starting drift detection run"
log_info "Config: $CONFIG_FILE"
log_info "Output format: $OUTPUT_FORMAT"
[ -n "$OUTPUT_FILE" ] && log_info "Output file: $OUTPUT_FILE"
[ ${#NOTIFY_CHANNELS[@]} -gt 0 ] && log_info "Notifications: ${NOTIFY_CHANNELS[*]}"
echo ""

# Preflight checks
check_prerequisites
validate_config "$CONFIG_FILE"
show_terraform_info

# Run detection
EXIT_CODE=0
run_detection || EXIT_CODE=$?

echo ""
echo "────────────────────────────────────────────────────────────"

case $EXIT_CODE in
    0)
        log_success "No drift detected. Infrastructure is in sync."
        ;;
    2)
        log_warn "Drift detected\! Review the report above for details."
        ;;
    *)
        log_error "Detection encountered an error (exit code: $EXIT_CODE)"
        ;;
esac

echo "────────────────────────────────────────────────────────────"
echo ""

exit $EXIT_CODE
