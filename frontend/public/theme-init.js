// Tun/kun rejimi sahifa chizilishidan oldin qo'llanadi (oq "chaqnash" bo'lmasin)
      try {
        var t = localStorage.getItem("aventos.theme");
        if (t !== "light" && t !== "dark") t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
        document.documentElement.dataset.theme = t;
      } catch (e) { /* standart — kun */ }
