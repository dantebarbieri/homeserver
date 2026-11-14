export function setupPwa(onError) {
  const section = document.getElementById("app-install"), button = document.getElementById("install-app");
  const standalone = matchMedia("(display-mode: standalone)");
  let prompt = null;
  const installed = () => { section.hidden = true; prompt = null; button.hidden = true; };
  if (standalone.matches || navigator.standalone) installed();
  standalone.addEventListener("change", () => { section.hidden = standalone.matches; });
  window.addEventListener("appinstalled", installed);
  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    prompt = event;
    section.hidden = false;
    button.hidden = false;
  });
  button.addEventListener("click", async () => {
    if (!prompt) return;
    const request = prompt;
    prompt = null;
    button.hidden = true;
    try {
      await request.prompt();
      await request.userChoice;
    } catch (error) {
      onError(`ChasEx installation failed: ${error.message}. You can still use the browser.`);
    }
  });
  if (!isSecureContext) {
    onError("ChasEx installation and offline support require HTTPS or localhost.");
  } else if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js", { scope: "./", updateViaCache: "none" })
      .catch(error => onError(`ChasEx offline support could not start: ${error.message}. Online viewing is still available.`));
  }
}
