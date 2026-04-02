#!/usr/bin/env bash

set -euo pipefail

REPO_API_URL="https://api.github.com/repos/Lifesigns-PD/orchestrator-releases/releases/latest"
GATEWAY_REPO_API_URL="https://api.github.com/repos/PD-dev-2025/gateway-dashboard-release/releases/latest"
SERVICE_NAME="go-ble-orchestrator"
INSTALL_DIR="/opt/go-ble-orchestrator"
GATEWAY_SERVICE_NAME="gateway-dashboard"
GATEWAY_INSTALL_DIR="/opt/gateway-dashboard"
GATEWAY_SERVICE_FILE="/etc/systemd/system/${GATEWAY_SERVICE_NAME}.service"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

require_cmd curl
require_cmd unzip
require_cmd sudo

if [ ! -f /etc/os-release ]; then
  echo "Cannot detect the operating system. This installer requires Ubuntu 22.04 or newer."
  exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release

if [ "${ID:-}" != "ubuntu" ]; then
  echo "Unsupported OS: ${PRETTY_NAME:-unknown}. This installer requires Ubuntu 22.04 or newer."
  exit 1
fi

ubuntu_major_version="${VERSION_ID%%.*}"
if [ -z "${ubuntu_major_version}" ] || [ "${ubuntu_major_version}" -lt 22 ]; then
  echo "Unsupported Ubuntu version: ${PRETTY_NAME:-unknown}."
  echo "Please upgrade this machine to Ubuntu 22.04 or newer, then run the installer again."
  exit 1
fi

prompt_yes_only() {
  local prompt_message="$1"
  local response

  read -r -p "${prompt_message}" response
  if [ "${response}" != "yes" ]; then
    echo "Aborted by user."
    exit 1
  fi
}

remove_dir_safely() {
  local target_dir="$1"
  local display_name="$2"
  local attempt

  if [ ! -d "${target_dir}" ]; then
    echo "No existing ${display_name} directory found."
    return 0
  fi

  prompt_yes_only "Are you sure you want to remove previous files from ${target_dir}? Type yes to continue: "

  echo "Removing existing ${target_dir} directory..."
  for attempt in 1 2 3; do
    sudo rm -rf "${target_dir}"
    if [ ! -e "${target_dir}" ]; then
      return 0
    fi
    sleep 1
  done

  echo "Failed to fully remove ${target_dir}."
  echo "This usually happens because some process is still writing inside it, or the filesystem is returning entries while removal is in progress."
  echo "Please check what is using the directory and try again."
  exit 1
}

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

echo "Fetching latest release metadata from orchestrator-releases..."
release_json="$(curl -fsSL "${REPO_API_URL}")"

zip_url="$(printf '%s\n' "${release_json}" | grep -oE '"browser_download_url":[[:space:]]*"[^"]+Installationsmain-[^"]+\.zip"' | head -n 1 | cut -d '"' -f 4)"
tag_name="$(printf '%s\n' "${release_json}" | grep -oE '"tag_name":[[:space:]]*"[^"]+"' | head -n 1 | cut -d '"' -f 4)"

if [ -z "${zip_url}" ]; then
  echo "Could not find an Installationsmain zip asset in the latest release."
  exit 1
fi

zip_path="${WORK_DIR}/Installationsmain.zip"

echo "Downloading latest release asset: ${tag_name:-unknown}"
curl -fL "${zip_url}" -o "${zip_path}"

echo "Unzipping release bundle..."
unzip -q "${zip_path}" -d "${WORK_DIR}"

bundle_dir="${WORK_DIR}/Installationsmain"
if [ ! -d "${bundle_dir}" ]; then
  echo "Unzipped bundle does not contain Installationsmain/"
  exit 1
fi

cd "${bundle_dir}"

echo "Making DeviceManager_Install.sh executable..."
chmod +x ./DeviceManager_Install.sh

echo "Stopping previous ${SERVICE_NAME} service if it exists..."
if sudo systemctl list-unit-files | grep -q "^${SERVICE_NAME}\.service"; then
  sudo systemctl stop "${SERVICE_NAME}" || true
  sudo systemctl disable "${SERVICE_NAME}" || true
fi

echo "Stopping any running ${SERVICE_NAME} process..."
sudo pkill -f "${SERVICE_NAME}" || true

remove_dir_safely "${INSTALL_DIR}" "go-ble-orchestrator"

echo "Starting installer..."
sudo ./DeviceManager_Install.sh
sudo systemctl enable "${SERVICE_NAME}" || true

read -r -p "Additionally you need to update the gateway-dashboard version. Type yes to continue: " update_gateway_dashboard
if [ "${update_gateway_dashboard}" != "yes" ]; then
  echo "Skipping gateway-dashboard update."
  exit 0
fi

echo "Fetching latest gateway-dashboard release metadata..."
gateway_release_json="$(curl -fsSL "${GATEWAY_REPO_API_URL}")"
gateway_zip_url="$(printf '%s\n' "${gateway_release_json}" | grep -oE '"browser_download_url":[[:space:]]*"[^"]+linux_amd64\.zip"' | head -n 1 | cut -d '"' -f 4)"
gateway_tag_name="$(printf '%s\n' "${gateway_release_json}" | grep -oE '"tag_name":[[:space:]]*"[^"]+"' | head -n 1 | cut -d '"' -f 4)"

if [ -z "${gateway_zip_url}" ]; then
  echo "Could not find a gateway-dashboard linux_amd64 zip asset in the latest release."
  exit 1
fi

gateway_work_dir="${WORK_DIR}/gateway-dashboard"
mkdir -p "${gateway_work_dir}"
gateway_zip_path="${gateway_work_dir}/gateway-dashboard_linux_amd64.zip"

echo "Downloading gateway-dashboard release: ${gateway_tag_name:-unknown}"
curl -fL "${gateway_zip_url}" -o "${gateway_zip_path}"

echo "Unzipping gateway-dashboard bundle..."
unzip -q "${gateway_zip_path}" -d "${gateway_work_dir}"

if [ ! -f "${gateway_work_dir}/gateway-dashboard" ]; then
  echo "gateway-dashboard binary not found in the downloaded bundle."
  exit 1
fi

if [ ! -f "${gateway_work_dir}/config.json.example" ]; then
  echo "config.json.example not found in the downloaded bundle."
  exit 1
fi

echo "Stopping previous ${GATEWAY_SERVICE_NAME} service if it exists..."
if sudo systemctl list-unit-files | grep -q "^${GATEWAY_SERVICE_NAME}\.service"; then
  sudo systemctl stop "${GATEWAY_SERVICE_NAME}" || true
  sudo systemctl disable "${GATEWAY_SERVICE_NAME}" || true
fi

echo "Stopping any running ${GATEWAY_SERVICE_NAME} process..."
sudo pkill -f "${GATEWAY_SERVICE_NAME}" || true

remove_dir_safely "${GATEWAY_INSTALL_DIR}" "gateway-dashboard"

echo "Creating ${GATEWAY_INSTALL_DIR}..."
sudo mkdir -p "${GATEWAY_INSTALL_DIR}"

echo "Preparing gateway-dashboard config.json..."
cp "${gateway_work_dir}/config.json.example" "${gateway_work_dir}/config.json"

read -r -p "Do you want to edit gateway-dashboard config.json now? Type yes to open sudo nano: " edit_gateway_config
if [ "${edit_gateway_config}" = "yes" ]; then
  sudo nano "${gateway_work_dir}/config.json"
fi

echo "Installing gateway-dashboard files..."
sudo cp "${gateway_work_dir}/gateway-dashboard" "${GATEWAY_INSTALL_DIR}/"
if [ -f "${gateway_work_dir}/README.md" ]; then
  sudo cp "${gateway_work_dir}/README.md" "${GATEWAY_INSTALL_DIR}/"
fi
sudo cp "${gateway_work_dir}/config.json" "${GATEWAY_INSTALL_DIR}/"
sudo chmod +x "${GATEWAY_INSTALL_DIR}/gateway-dashboard"

echo "Creating ${GATEWAY_SERVICE_FILE}..."
sudo tee "${GATEWAY_SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=Gateway Dashboard Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${GATEWAY_INSTALL_DIR}
ExecStart=${GATEWAY_INSTALL_DIR}/gateway-dashboard
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${GATEWAY_SERVICE_NAME}

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd and starting ${GATEWAY_SERVICE_NAME}..."
sudo systemctl daemon-reload
sudo systemctl enable "${GATEWAY_SERVICE_NAME}"
sudo systemctl start "${GATEWAY_SERVICE_NAME}"

echo "gateway-dashboard installed and started successfully."
