// Apply the saved theme before the first paint (no flash of the wrong theme).
// A separate file because the page's Content Security Policy forbids inline scripts.
(function () {
  var theme = "system"
  try {
    theme = JSON.parse(localStorage.getItem("omnirag.theme") || '"system"')
  } catch (e) {}
  var dark = theme === "dark" || (theme !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches)
  document.documentElement.classList.toggle("dark", dark)
})()
