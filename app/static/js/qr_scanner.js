document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    const readerParent = document.querySelector(".scanner-viewport");
    const startBtn = document.getElementById("btn-start");
    const stopBtn = document.getElementById("btn-stop");
    const promptBlock = document.getElementById("prompt-block");
    const statusBadge = document.getElementById("scanner-status");
    const resultContainer = document.getElementById("result-container");
    const resultSpan = document.getElementById("result");
    const errorBox = document.getElementById("scanner-error");

    let html5Qrcode = null;

    //function to handle the QR code scanning when the code is scanned successfully
    function onScanSuccess(decodedText, decodedResult) {
        console.log("QR Code Scanned:", decodedText);

        if (resultSpan) resultSpan.textContent = decodedText;
        if (resultContainer) resultContainer.classList.remove("d-none");
        let sanitizedTrapId = processQRCode(decodedText);

        setTimeout(() => {
            if (sanitizedTrapId) {
                window.location.href = `/traps/${encodeURIComponent(sanitizedTrapId)}`;
            }
        }, 1000);
        if (navigator.vibrate) {
            navigator.vibrate(100);
        }
    }

    //function to sanitize the QR code input
    function processQRCode(scannedText) {
        // Clean the text: trim spaces, uppercase it, and remove accidental newlines
        let cleanText = scannedText.trim().toUpperCase().replace(/[\r\n]/g, '');

        //  Extract just the numbers if they scanned a messy string or full URL
        // Matches 'STT-' followed by digits anywhere in the scanned text
        const patternMatch = cleanText.match(/STT-[0-9]+/);

        if (patternMatch) {
            const finalValidInput = patternMatch[0]; // Extracts exactly "STT-XXXXX"
            console.log("Valid QR Code Processed:", finalValidInput);
            return finalValidInput;
        } else {
            console.error("Invalid QR Code: Pattern 'STT-<number>' not found.");
            alert("Invalid QR Code format. Please scan a valid QR Code.");
            return null;
        }
    }

    async function startScanner() {
        if (errorBox) {
            errorBox.classList.add("d-none");
            errorBox.textContent = "";
        }

        if (!window.Html5Qrcode) {
            showError("QR Scanner library failed to load. Check your internet connection.");
            return;
        }

        // Modern browsers require HTTPS or localhost/127.0.0.1 for camera access
        const isSecure = location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1";
        if (!isSecure) {
            showError("Camera access blocked: Browsers require HTTPS or localhost to access camera devices.");
            return;
        }

        if (startBtn) startBtn.classList.add("d-none");
        if (stopBtn) stopBtn.classList.remove("d-none");
        if (promptBlock) promptBlock.classList.add("d-none");
        if (statusBadge) {
            statusBadge.innerText = "Initializing...";
            statusBadge.className = "badge bg-warning text-dark";
        }

        try {
            if (html5Qrcode) {
                try {
                    await html5Qrcode.clear();
                } catch (e) { }
            }

            html5Qrcode = new Html5Qrcode("reader");

            // Query available camera devices first
            const devices = await Html5Qrcode.getCameras();

            if (!devices || devices.length === 0) {
                showError("No camera device found on this system.");
                resetUIState();
                return;
            }

            // Prefer rear/back camera if available, otherwise select first camera
            const backCam = devices.find(d => /back|rear|environment/i.test(d.label));
            const chosenCamId = backCam ? backCam.id : devices[0].id;

            const scanConfig = {
                fps: 10,
                qrbox: (viewfinderWidth, viewfinderHeight) => {
                    const minDim = Math.min(viewfinderWidth || 250, viewfinderHeight || 250);
                    const size = Math.floor(minDim * 0.7);
                    return { width: Math.max(size, 150), height: Math.max(size, 150) };
                }
            };

            await html5Qrcode.start(
                chosenCamId,
                scanConfig,
                onScanSuccess,
                (errorMessage) => {
                    // Frame match errors ignored
                }
            );

            if (statusBadge) {
                statusBadge.innerText = "Live Scanning";
                statusBadge.className = "badge bg-success text-white";
            }
            if (readerParent) {
                readerParent.classList.add("scanner-laser-container");
            }
        } catch (err) {
            console.error("Camera start failure:", err);
            // Fallback try with facingMode constraint if camera ID start fails
            try {
                const scanConfigFallback = { fps: 10, qrbox: { width: 220, height: 220 } };
                await html5Qrcode.start(
                    { facingMode: "environment" },
                    scanConfigFallback,
                    onScanSuccess,
                    (e) => { }
                );
                if (statusBadge) {
                    statusBadge.innerText = "Live Scanning";
                    statusBadge.className = "badge bg-success text-white";
                }
                if (readerParent) {
                    readerParent.classList.add("scanner-laser-container");
                }
            } catch (fallbackErr) {
                console.error("Fallback camera failure:", fallbackErr);
                let msg = fallbackErr.message || err.message || fallbackErr || "Camera permission denied or camera unavailable.";
                showError("Camera Initialization Failed: " + msg);
                resetUIState();
            }
        }
    }

    function stopScanner() {
        if (html5Qrcode) {
            html5Qrcode.stop().then(() => {
                html5Qrcode.clear();
                resetUIState();
            }).catch((err) => {
                console.error("Error stopping scanner:", err);
                resetUIState();
            });
        } else {
            resetUIState();
        }
    }

    function resetUIState() {
        if (startBtn) startBtn.classList.remove("d-none");
        if (stopBtn) stopBtn.classList.add("d-none");
        if (promptBlock) promptBlock.classList.remove("d-none");
        if (statusBadge) {
            statusBadge.innerText = "Camera Off";
            statusBadge.className = "badge bg-secondary text-white";
        }
        if (readerParent) {
            readerParent.classList.remove("scanner-laser-container");
        }
    }

    function showError(msg) {
        if (errorBox) {
            errorBox.textContent = msg;
            errorBox.classList.remove("d-none");
        }
    }

    // Attach event listeners
    if (startBtn) {
        startBtn.addEventListener("click", startScanner);
    }
    if (stopBtn) {
        stopBtn.addEventListener("click", stopScanner);
    }
});
