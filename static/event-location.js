(() => {
  const leaflet = window.L;
  const pinZoom = 16;
  const defaultMapCenter = [12.88, 121.77];
  const searchLimit = 6;

  function readPin(latitude, longitude) {
    if (latitude == null || longitude == null || latitude === "" || longitude === "") return null;
    const lat = Number(latitude);
    const lng = Number(longitude);
    return lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180 ? [lat, lng] : null;
  }

  function createMap(element, center, zoom) {
    element.hidden = false;
    const map = leaflet.map(element, { scrollWheelZoom: false }).setView(center, zoom);
    leaflet.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      referrerPolicy: "strict-origin-when-cross-origin",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    return map;
  }

  // Include nearby administrative areas to distinguish places with the same name.
  function locationLabel(place) {
    const streetAddress = [place.housenumber, place.street].filter(Boolean).join(" ");
    const parts = [place.name, streetAddress, place.district, place.locality, place.city,
      place.county, place.state, place.country];
    return [...new Set(parts.filter(Boolean))].join(", ");
  }

  function setupSearch(picker, placePin) {
    const searchPanel = picker.querySelector("[data-location-search]");
    const input = searchPanel.querySelector('input[type="search"]');
    const button = searchPanel.querySelector("[data-search-location]");
    const status = searchPanel.querySelector("[data-search-status]");
    const results = searchPanel.querySelector("[data-location-results]");
    const venue = picker.closest("form").querySelector('[name="venue"]');
    let activeSearch;
    let autoFilledVenue;

    function clearSearch() {
      activeSearch?.abort();
      activeSearch = null;
      results.hidden = true;
      results.replaceChildren();
      status.textContent = "";
    }

    function addResult(label, pin) {
      const item = document.createElement("li");
      const choice = document.createElement("button");
      choice.type = "button";
      choice.className = "event-location-result";
      choice.textContent = label;
      choice.addEventListener("click", () => {
        placePin(pin);
        input.value = label.slice(0, input.maxLength);
        // Keep a venue label the organizer entered, such as a room name.
        if (!venue.value.trim() || venue.value === autoFilledVenue) {
          autoFilledVenue = label.slice(0, venue.maxLength);
          venue.value = autoFilledVenue;
        }
        clearSearch();
        button.focus();
      });
      item.append(choice);
      results.append(item);
    }

    async function search() {
      if (activeSearch) return;
      clearSearch();
      const query = input.value.trim();
      if (query.length < 2) {
        status.textContent = "Enter a place name or address to search.";
        return;
      }

      // Use the default map area to rank results and keep locations worldwide searchable.
      const params = new URLSearchParams({
        q: query, limit: searchLimit, lat: defaultMapCenter[0], lon: defaultMapCenter[1], zoom: 5,
      });
      const request = new AbortController();
      activeSearch = request;
      const timeout = window.setTimeout(() => request.abort(), 8000);
      status.textContent = "Searching for locations…";
      try {
        const response = await fetch(`https://photon.komoot.io/api/?${params}`, { signal: request.signal });
        if (!response.ok) throw new Error("Location search failed");
        const { features } = await response.json();
        if (activeSearch !== request) return;

        for (const feature of features.slice(0, searchLimit)) {
          const geometry = feature?.geometry;
          if (geometry?.type !== "Point" || !Array.isArray(geometry.coordinates)) continue;
          // GeoJSON points put longitude before latitude.
          const [lng, lat] = geometry.coordinates;
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
          const pin = readPin(lat, lng);
          const label = locationLabel(feature.properties ?? {});
          if (pin && label) addResult(label, pin);
        }
        results.hidden = results.childElementCount === 0;
        status.textContent = results.hidden
          ? "No matches. Try including the city or a nearby landmark."
          : "Select a match to set the map pin.";
      } catch {
        if (activeSearch === request) status.textContent = "Location search is unavailable. Try again in a moment.";
      } finally {
        window.clearTimeout(timeout);
        if (activeSearch === request) activeSearch = null;
      }
    }

    function copyVenueToSearch() {
      if (!picker.matches("details:not([open])") && !input.value) {
        input.value = venue.value.trim().slice(0, input.maxLength);
      }
    }

    searchPanel.hidden = false;
    copyVenueToSearch();
    picker.addEventListener("toggle", copyVenueToSearch);
    input.addEventListener("input", clearSearch);
    button.addEventListener("click", search);
    // Enter searches for the venue instead of submitting the event form.
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        search();
      }
    });
  }

  function setupPicker(picker) {
    const latitude = picker.querySelector('[name="latitude"]');
    const longitude = picker.querySelector('[name="longitude"]');
    const locate = picker.querySelector("[data-use-current-location]");
    const clear = picker.querySelector("[data-clear-location]");
    const status = picker.querySelector("[data-location-status]");
    const instructions = leaflet
      ? "Search for the venue or click the map to set a pin."
      : "Search for the venue or use your current location to set a pin.";
    let map;
    let marker;
    let locationRequest = 0;

    picker.querySelector("[data-location-actions]").hidden = false;
    status.textContent = readPin(latitude.value, longitude.value) ? "Map pin selected." : instructions;

    function updateMarker(recenter = false) {
      const pin = readPin(latitude.value, longitude.value);
      picker.toggleAttribute("data-location-selected", Boolean(pin));
      clear.disabled = !latitude.value && !longitude.value;
      if (!map) return;
      if (!pin) {
        marker?.remove();
        marker = null;
        return;
      }

      if (marker) marker.setLatLng(pin);
      else marker = leaflet.marker(pin, { alt: "Selected event venue" }).addTo(map);
      if (recenter) map.setView(pin, pinZoom);
    }

    function cancelLocationRequest() {
      locationRequest += 1;
      locate.disabled = false;
    }

    function placePin([lat, lng], recenter = true) {
      cancelLocationRequest();
      latitude.value = lat.toFixed(6);
      longitude.value = lng.toFixed(6);
      updateMarker(recenter);
      status.textContent = "Map pin selected.";
    }

    function showMap() {
      if (picker.matches("details:not([open])") || !leaflet) return;
      if (map) {
        map.invalidateSize({ pan: false });
        return;
      }

      // Open unpinned events over the Philippines without assigning a location.
      const pin = readPin(latitude.value, longitude.value);
      map = createMap(picker.querySelector("[data-location-map]"), pin || defaultMapCenter, pin ? pinZoom : 5);
      updateMarker();
      map.on("click", (event) => {
        const { lat, lng } = map.wrapLatLng(event.latlng);
        placePin([lat, lng], false);
      });
    }

    locate.addEventListener("click", () => {
      if (!navigator.geolocation) {
        status.textContent = "Current location is unavailable. " + instructions;
        return;
      }

      const request = ++locationRequest;
      locate.disabled = true;
      status.textContent = "Finding your current location…";
      navigator.geolocation.getCurrentPosition(
        ({ coords }) => {
          if (request !== locationRequest) return;
          placePin([coords.latitude, coords.longitude]);
        },
        () => {
          if (request !== locationRequest) return;
          locate.disabled = false;
          status.textContent = "Could not get your current location. " + instructions;
        },
        { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 },
      );
    });

    clear.addEventListener("click", () => {
      cancelLocationRequest();
      latitude.value = "";
      longitude.value = "";
      updateMarker();
      status.textContent = instructions;
    });
    picker.addEventListener("toggle", showMap);
    setupSearch(picker, placePin);
    updateMarker();
    showMap();
  }

  for (const picker of document.querySelectorAll("[data-event-location-picker]")) {
    setupPicker(picker);
  }

  if (leaflet) {
    for (const preview of document.querySelectorAll("[data-event-location-preview]")) {
      const pin = readPin(preview.dataset.latitude, preview.dataset.longitude);
      if (!pin) continue;
      const map = createMap(preview, pin, pinZoom);
      leaflet.marker(pin, { alt: "Event venue" }).addTo(map);
    }
  }
})();
