const status = document.getElementById("pwa-status");
const button = document.getElementById("install-app");
let installPrompt = null;
window.addEventListener("beforeinstallprompt", event => {
  event.preventDefault();
  installPrompt = event;
  button.hidden = false;
});
button.onclick = async () => {
  if (!installPrompt) return;
  try {
    await installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    button.hidden = true;
  } catch (error) {
    status.textContent = `Installation could not start: ${error.message}`;
  }
};
window.addEventListener("appinstalled", () => {
  button.hidden = true;
  status.textContent = "Installed. Live telemetry still requires your authenticated session.";
});
if ("serviceWorker" in navigator && isSecureContext) {
  navigator.serviceWorker.addEventListener("message", event => {
    if (event.data?.type === "attacks-cache-error") status.textContent = "Offline app assets could not be saved; live browsing still works.";
  });
  navigator.serviceWorker.register("/sw.js", {type: "module", scope: "/", updateViaCache: "none"}).then(registration => {
    const installing = registration.installing;
    installing?.addEventListener("statechange", () => {
      if (installing.state === "redundant" && !registration.active)
        status.textContent = "Offline app setup failed. Reload while signed in and connected.";
    });
  }).catch(error => { status.textContent = `Offline app setup unavailable: ${error.message}`; });
} else {
  status.textContent = "Home-screen app support requires HTTPS and a supported browser.";
}
