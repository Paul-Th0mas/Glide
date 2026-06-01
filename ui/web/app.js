// Glide Frontend Logic

let allMonitors = [];
let calibrationBoundaries = [];
let currentBoundaryIndex = 0;
let configData = { calibration: null, hotkey: 'caps lock+shift' };

// Port for MJPEG streaming server (served by python backend)
const MJPEG_PORT = 5000;

document.addEventListener('DOMContentLoaded', () => {
    // Initial load: wait for pywebview to be ready
    if (window.pywebview) {
        initApp();
    } else {
        window.addEventListener('pywebviewready', initApp);
    }
});

async function initApp() {
    console.log("pywebview API ready. Initializing...");
    try {
        await loadMonitors();
        await loadSettings();
    } catch (e) {
        console.error("Error initializing app:", e);
    }
}

// ----------------------------------------------------
// Navigation / View Router
// ----------------------------------------------------
function showView(viewId) {
    // Hide all views
    document.querySelectorAll('.view-panel').forEach(panel => {
        panel.style.display = 'none';
    });

    // Show target view
    document.getElementById(viewId).style.display = 'block';

    // Update nav links active state
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
    });

    if (viewId === 'onboarding-view') {
        document.getElementById('nav-home').classList.add('active');
        stopCameraFeed();
    } else if (viewId === 'calibrate-view') {
        document.getElementById('nav-calibrate').classList.add('active');
        startCameraFeed();
    } else if (viewId === 'settings-view') {
        document.getElementById('nav-settings').classList.add('active');
        stopCameraFeed();
    }
}

// ----------------------------------------------------
// Monitor Layout Rendering
// ----------------------------------------------------
async function loadMonitors() {
    if (!window.pywebview || !window.pywebview.api) return;

    try {
        allMonitors = await window.pywebview.api.get_monitors();
        console.log("Monitors loaded:", allMonitors);
        
        renderMonitorsGrid('onboarding-monitors-grid', allMonitors);
        renderMonitorsGrid('settings-monitors-grid', allMonitors);
    } catch (e) {
        console.error("Failed to load monitors:", e);
    }
}

function renderMonitorsGrid(containerId, monitors, activeStep = null) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!monitors || monitors.length === 0) {
        container.innerHTML = `<div style="color: var(--text-muted);">No monitors detected.</div>`;
        return;
    }

    container.innerHTML = '';

    monitors.forEach(monitor => {
        const node = document.createElement('div');
        node.className = 'monitor-node';
        node.id = `${containerId}-monitor-${monitor.index}`;
        
        // Extract dimensions
        const [left, top, right, bottom] = monitor.rect;
        const width = right - left;
        const height = bottom - top;

        // Is it part of the active calibration?
        let isCalibrating = false;
        if (activeStep && monitor.index === activeStep.monitor_index) {
            isCalibrating = true;
            node.classList.add('calibrating');
        }

        if (monitor.is_primary) {
            node.classList.add('primary');
        }

        // Label details
        let badgeHtml = '';
        if (monitor.is_primary) {
            badgeHtml = `<span class="monitor-badge">Primary</span>`;
        } else if (isCalibrating) {
            badgeHtml = `<span class="monitor-badge green">Calibrating</span>`;
        }

        // Add corner dots and center dot
        const cornerDotsHtml = `
            <div class="corner-dot top-left ${isCalibrating && activeStep.corner === 'top_left' ? 'active' : ''}"></div>
            <div class="corner-dot top-right ${isCalibrating && activeStep.corner === 'top_right' ? 'active' : ''}"></div>
            <div class="corner-dot bottom-left ${isCalibrating && activeStep.corner === 'bottom_left' ? 'active' : ''}"></div>
            <div class="corner-dot bottom-right ${isCalibrating && activeStep.corner === 'bottom_right' ? 'active' : ''}"></div>
            <div class="center-dot ${isCalibrating && activeStep.type === 'center' ? 'active' : ''}"></div>
        `;

        node.innerHTML = `
            ${cornerDotsHtml}
            ${badgeHtml}
            <span class="monitor-name">Monitor ${monitor.index + 1}</span>
            <span class="monitor-resolution">${width} × ${height}</span>
        `;
        
        container.appendChild(node);
    });
}

// ----------------------------------------------------
// Camera Preview Stream
// ----------------------------------------------------
function startCameraFeed() {
    const img = document.getElementById('camera-stream');
    const loading = document.getElementById('camera-loading');
    
    if (img && loading) {
        img.style.display = 'none';
        loading.style.display = 'flex';
        
        // Connect to local HTTP server MJPEG feed
        img.src = `http://localhost:${MJPEG_PORT}/video_feed?t=${new Date().getTime()}`;
        
        img.onload = () => {
            loading.style.display = 'none';
            img.style.display = 'block';
        };
        
        img.onerror = () => {
            // Retry once after 1 second if the server is still starting
            setTimeout(() => {
                img.src = `http://localhost:${MJPEG_PORT}/video_feed?t=${new Date().getTime()}`;
            }, 1000);
        };
    }
}

function stopCameraFeed() {
    const img = document.getElementById('camera-stream');
    if (img) {
        img.src = '';
        img.style.display = 'none';
    }
}

// ----------------------------------------------------
// Calibration Wizard State Machine
// ----------------------------------------------------
async function startCalibrationFlow() {
    if (!window.pywebview || !window.pywebview.api) return;

    showView('calibrate-view');
    currentStepIndex = 0;
    
    try {
        // Notify backend we are calibrating (turns on camera feed)
        await window.pywebview.api.start_calibration();
        
        // Fetch corners that need calibration
        calibrationSteps = await window.pywebview.api.get_calibration_steps();
        console.log("Calibration steps needed:", calibrationSteps);

        if (calibrationSteps.length === 0) {
            document.getElementById('calibration-instruction').innerHTML = 
                `<span style="color: var(--accent-cyan)">Single Monitor Detected.</span><br/>Glide requires at least 2 connected monitors.`;
            document.getElementById('calibration-progress').textContent = 'Step 0 of 0';
            return;
        }

        // Initialize empty monitors array in configData
        configData.calibration = {
            monitors: [],
            created_at: new Date().toISOString()
        };

        runCalibrationStep();
    } catch (e) {
        console.error("Failed to start calibration:", e);
    }
}

function runCalibrationStep() {
    if (currentStepIndex >= calibrationSteps.length) {
        finishCalibration();
        return;
    }

    const step = calibrationSteps[currentStepIndex];
    
    // Highlight monitor and target in preview
    renderMonitorsGrid('calibration-monitors-grid', allMonitors, step);

    // Update instruction text and progress indicator
    document.getElementById('calibration-progress').textContent = `Step ${currentStepIndex + 1} of ${calibrationSteps.length}`;
    
    const isCenter = step.type === 'center';
    
    if (isCenter) {
        document.getElementById('calibration-instruction').innerHTML = 
            `Look at the <span style="color: var(--accent-cyan)">centre</span> of Monitor ${step.monitor_index + 1}.`;
    } else {
        const cornerLabels = {
            "top_left": "Top-Left",
            "top_right": "Top-Right",
            "bottom_left": "Bottom-Left",
            "bottom_right": "Bottom-Right"
        };
        const cornerLabel = cornerLabels[step.corner];
        document.getElementById('calibration-instruction').innerHTML = 
            `Look at the <span style="color: var(--accent-cyan)">${cornerLabel}</span> corner of Monitor ${step.monitor_index + 1}.`;
    }

    // Start 3-second preparation countdown
    startCountdown(3, async () => {
        if (isCenter) {
            document.getElementById('calibration-instruction').innerHTML = 
                `Keep looking at the <span style="color: var(--accent-green)">centre</span>...`;
        } else {
            const cornerLabels = {
                "top_left": "Top-Left",
                "top_right": "Top-Right",
                "bottom_left": "Bottom-Left",
                "bottom_right": "Bottom-Right"
            };
            const cornerLabel = cornerLabels[step.corner];
            document.getElementById('calibration-instruction').innerHTML = 
                `Keep looking at the <span style="color: var(--accent-green)">${cornerLabel} corner</span>...`;
        }
            
        // Tell python backend to collect samples
        await window.pywebview.api.start_sampling();
        
        // Run 3-second sampling timer
        startCountdown(3, async () => {
            // Sampling completed! Stop and get threshold
            const angles = await window.pywebview.api.stop_sampling_corner();
            console.log(`Calibrated angles for Monitor ${step.monitor_index + 1} ${isCenter ? 'center' : step.corner}:`, angles);
            
            // Store calibration data
            let mon = configData.calibration.monitors.find(m => m.index === step.monitor_index);
            if (!mon) {
                let mInfo = allMonitors.find(m => m.index === step.monitor_index);
                mon = {
                    index: step.monitor_index,
                    rect: mInfo.rect,
                    center: mInfo.center,
                    corners: {},
                    center_yaw: 0.0,
                    center_pitch: 0.0
                };
                configData.calibration.monitors.push(mon);
            }
            if (isCenter) {
                mon.center_yaw = angles[0];
                mon.center_pitch = angles[1];
            } else {
                mon.corners[step.corner] = angles;
            }
            
            // Advance step
            currentStepIndex++;
            
            // Short delay and auto-advance
            setTimeout(runCalibrationStep, 800);
        });
    });
}

function startCountdown(seconds, callback) {
    const timerWrapper = document.getElementById('calibration-timer-wrapper');
    const timerText = document.getElementById('timer-text');
    const progressCircle = document.getElementById('timer-progress-bar');
    
    timerWrapper.style.display = 'flex';
    timerText.textContent = seconds;
    
    const totalCircumference = 283; // 2 * PI * r (r=45)
    progressCircle.style.strokeDashoffset = 0;
    
    let timeLeft = seconds;
    const intervalTime = 50; // Update every 50ms for smooth circle animation
    const steps = (seconds * 1000) / intervalTime;
    let currentStep = 0;
    
    const interval = setInterval(() => {
        currentStep++;
        const percent = currentStep / steps;
        
        // Shrink the dashoffset
        progressCircle.style.strokeDashoffset = totalCircumference * percent;
        
        // Update integer countdown text
        const newTimeLeft = Math.ceil(seconds - (currentStep * intervalTime / 1000));
        if (newTimeLeft !== timeLeft && newTimeLeft >= 0) {
            timeLeft = newTimeLeft;
            timerText.textContent = timeLeft;
        }
        
        if (currentStep >= steps) {
            clearInterval(interval);
            timerWrapper.style.display = 'none';
            callback();
        }
    }, intervalTime);
}

async function cancelCalibration() {
    if (window.pywebview && window.pywebview.api) {
        await window.pywebview.api.stop_calibration();
    }
    showView('onboarding-view');
}

async function finishCalibration() {
    document.getElementById('calibration-instruction').innerHTML = 
        `<span style="color: var(--accent-green)">Calibration Complete!</span><br/>Saving configuration...`;
    
    configData.calibration.created_at = new Date().toISOString();
    
    if (window.pywebview && window.pywebview.api) {
        await window.pywebview.api.save_config(configData);
        await window.pywebview.api.stop_calibration();
        
        // Wait 1.5 seconds and close window
        setTimeout(async () => {
            await window.pywebview.api.close_ui();
        }, 1500);
    }
}

// ----------------------------------------------------
// Settings Form Logic
// ----------------------------------------------------
async function loadSettings() {
    if (!window.pywebview || !window.pywebview.api) return;

    try {
        configData = await window.pywebview.api.get_config();
        console.log("Config loaded:", configData);
        
        // Select matching option
        const presetSelect = document.getElementById('hotkey-preset');
        const customInput = document.getElementById('hotkey-custom-input');
        
        const knownPresets = ['caps lock+shift', 'ctrl+shift', 'alt+shift', 'caps lock'];
        
        if (knownPresets.includes(configData.hotkey)) {
            presetSelect.value = configData.hotkey;
            customInput.style.display = 'none';
        } else {
            presetSelect.value = 'custom';
            customInput.value = configData.hotkey;
            customInput.style.display = 'block';
        }
    } catch (e) {
        console.error("Failed to load settings:", e);
    }
}

function onPresetChange(value) {
    const customInput = document.getElementById('hotkey-custom-input');
    if (value === 'custom') {
        customInput.style.display = 'block';
        customInput.value = '';
        customInput.focus();
    } else {
        customInput.style.display = 'none';
        configData.hotkey = value;
    }
}

function validateCustomHotkey(value) {
    // Simple verification: must have characters and if keys are combined, joined with +
    const trimmed = value.trim().toLowerCase();
    if (trimmed) {
        configData.hotkey = trimmed;
    }
}

async function saveSettings() {
    if (!window.pywebview || !window.pywebview.api) return;
    
    // Save to configuration
    try {
        await window.pywebview.api.save_config(configData);
        alert("Settings saved successfully!");
        await window.pywebview.api.close_ui();
    } catch (e) {
        console.error("Failed to save settings:", e);
        alert("Error saving settings.");
    }
}
