function switchTheme() {
  const currentStyle = currentTheme();

  if (currentStyle == 'light') {
    setTheme('dark');
  }
  else {
    setTheme('light');
  }
}

function setTheme(style) {
  document.querySelectorAll('.isInitialToggle').forEach(elem => {
    elem.classList.remove('isInitialToggle');
  });
  document.documentElement.setAttribute('data-color-mode', style);
  localStorage.setItem('data-color-mode', style);
}

function currentTheme() {
  const localStyle = localStorage.getItem('data-color-mode');
  const defaultStyle = 'dark';
  return localStyle || defaultStyle;
}

(() => {
  setTheme(currentTheme());
})();
