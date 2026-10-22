// Använd HA:s inbyggda Lit om tillgängligt, annars fallback till CDN
const getLit = async () => {
  // Home Assistant 2023.4+ exponerar Lit globalt
  if (window.LitElement && window.litHtml) {
    return {
      LitElement: window.LitElement,
      html: window.litHtml.html,
      css: window.litHtml.css,
    };
  }
  // Fallback för äldre HA-versioner eller fristående testning
  return import('https://unpkg.com/lit@3.1.0?module');
};

const { LitElement, html, css } = await getLit();

const fireIcon = new URL('./fire.svg', import.meta.url).href;
const waterShortageIcon = new URL('./waterShortage.svg', import.meta.url).href;
const temperatureIcon = new URL('./temperature.svg', import.meta.url).href;
const yellowWarningIcon = new URL('./yellowWarning.svg', import.meta.url).href;
const orangeWarningIcon = new URL('./orangeWarning.svg', import.meta.url).href;
const redWarningIcon = new URL('./redWarning.svg', import.meta.url).href;

const LEAFLET_CSS_HREF = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
const LEAFLET_JS_SRC = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
const LEAFLET_ESM_URL = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet-src.esm.js';
const OSM_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';
const MAP_TILE_REFERRER_POLICY = 'strict-origin-when-cross-origin';
const DEFAULT_MAP_TILE_MAX_ZOOM = 18;
const MAX_MAP_TILE_MAX_ZOOM = 22;
const FIRE_RISK_VALUES = {
  forest_fire_risk: ['very_low', 'low', 'moderate', 'high', 'very_high', 'extreme'],
  grass_fire_risk: ['snow_covered', 'season_over', 'low', 'moderate', 'high', 'very_high'],
  forest_dryness: ['very_wet', 'wet', 'moderately_wet', 'dry', 'very_dry', 'extremely_dry'],
};
const THUNDER_SOURCE_KIND = 'local_thunder_probability_forecast';

const normalizeMapTileConfig = (config) => {
  const tileUrl = String(config.map_tile_url || '').trim();
  const attribution = String(config.map_tile_attribution || '').trim();
  const rawMaxZoom = config.map_tile_max_zoom;
  const maxZoom = rawMaxZoom === '' || rawMaxZoom === null || rawMaxZoom === undefined
    ? DEFAULT_MAP_TILE_MAX_ZOOM
    : Number(rawMaxZoom);

  if (!Number.isInteger(maxZoom) || maxZoom < 0 || maxZoom > MAX_MAP_TILE_MAX_ZOOM) {
    throw new Error(`Map tile max zoom must be an integer between 0 and ${MAX_MAP_TILE_MAX_ZOOM}.`);
  }

  if (tileUrl) {
    if (!tileUrl.includes('{z}') || !tileUrl.includes('{x}') || !tileUrl.includes('{y}')) {
      throw new Error('Custom map tile URL must include {z}, {x}, and {y}.');
    }

    let parsedUrl;
    try {
      parsedUrl = new URL(tileUrl, window.location.href);
    } catch (err) {
      throw new Error('Custom map tile URL is invalid.', { cause: err });
    }

    const isSameOrigin = parsedUrl.origin === window.location.origin;
    if (parsedUrl.protocol !== 'https:' && !isSameOrigin) {
      throw new Error('Custom map tile URL must use HTTPS or be same-origin.');
    }
    if (!attribution) {
      throw new Error('Custom map tile attribution is required.');
    }
  }

  config.map_tile_url = tileUrl || null;
  config.map_tile_attribution = tileUrl ? attribution : null;
  config.map_tile_max_zoom = maxZoom;
  return config;
};

class SmhiAlertCard extends LitElement {
  static properties = {
    hass: {},
    config: {},
    _expanded: {},
  };

  static styles = css`
    :host {
      /* Strength of the severity-tinted background when enabled (used in color-mix) */
      --smhi-alert-bg-strong: 22%;
      --smhi-alert-bg-soft: 12%;
      /* Optical vertical adjustment for the title in compact (1-row) mode */
      --smhi-alert-compact-title-offset: 2px;
      /* Outer horizontal padding for the list (set to 0 to align with other cards) */
      --smhi-alert-outer-padding: 0px;
      display: block;
    }

    ha-card {
      /* Keep the container tight so stacking multiple transparent cards doesn't show "gaps" */
      padding: 0;
      background: transparent;
      box-shadow: none;
      border: none;
      --ha-card-background: transparent;
      --ha-card-border-width: 0;
      --ha-card-border-color: transparent;
    }
    .alerts {
      display: flex;
      flex-direction: column;
      gap: 8px;
      /* No vertical padding: otherwise it becomes visible whitespace between stacked cards */
      padding: 0 var(--smhi-alert-outer-padding, 0px);
    }
    .area-group {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .alert {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 12px;
      align-items: start;
      padding: 12px;
      border-radius: var(--smhi-alert-border-radius, 8px);
      border: 1px solid var(--divider-color);
      background: var(--card-background-color);
      position: relative;
    }
    /* Compact (single-line) layout: vertically center the whole row */
    .alert.compact {
      align-items: center;
    }

    /* Optional severity-tinted background (keeps normal card background as base) */
    .alert.bg-severity {
      background: linear-gradient(
          90deg,
          color-mix(in srgb, var(--smhi-accent) var(--smhi-alert-bg-strong, 22%), var(--card-background-color)) 0%,
          color-mix(in srgb, var(--smhi-accent) var(--smhi-alert-bg-soft, 12%), var(--card-background-color)) 55%,
          var(--card-background-color) 100%
        );
    }
    .alert::before {
      content: '';
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: 4px;
      border-top-left-radius: inherit;
      border-bottom-left-radius: inherit;
      background: var(--smhi-accent, var(--primary-color));
    }
    .alert.sev-yellow { --smhi-accent: var(--smhi-alert-yellow, #f1c40f); }
    .alert.sev-orange { --smhi-accent: var(--smhi-alert-orange, #e67e22); }
    .alert.sev-red { --smhi-accent: var(--smhi-alert-red, var(--error-color, #e74c3c)); }
    .alert.sev-message { --smhi-accent: var(--smhi-alert-message, var(--primary-color)); }

    .icon {
      width: 32px;
      height: 32px;
      margin-inline-start: 4px;
      margin-top: 2px;
    }
    .icon-col {
      display: flex;
      align-items: flex-start;
    }
    .icon-col.compact {
      align-items: center;
    }
    .content {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }
    /* Allow the content column to fill the alert height in normal (multi-line) layout */
    .content {
      align-self: stretch;
    }
    /* In compact layout, don't stretch the content; let the grid center it precisely */
    .content.compact {
      align-self: center;
    }
    .title {
      display: flex;
      gap: 8px;
      align-items: center;
      min-width: 0;
    }
    .district {
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1 1 auto;
      min-width: 0;
    }
    /* In compact mode, apply a tiny optical offset so the text looks centered */
    .district.compact {
      transform: translateY(var(--smhi-alert-compact-title-offset, 1px));
      line-height: 1;
    }
    .meta {
      color: var(--secondary-text-color);
      font-size: 0.9em;
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
    }
    .details {
      margin-top: 6px;
    }
    .md-text {
      white-space: pre-wrap;
      line-height: 1.5;
      font-family: inherit;
      font-size: 0.95em;
      color: var(--primary-text-color);
      overflow-wrap: anywhere;
    }
    .details-text {
      display: flex;
      flex-direction: column;
      gap: 12px;
      line-height: 1.5;
      font-family: inherit;
      font-size: 0.95em;
      color: var(--primary-text-color);
      overflow-wrap: anywhere;
    }
    .details-section {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .details-heading {
      font-weight: 600;
      font-size: 1em;
    }
    .details-paragraph {
      margin: 0;
    }
    .details-list {
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 6px;
    }
    .details-list li {
      margin: 0;
    }
    .details-toggle {
      color: var(--primary-color);
      cursor: pointer;
      user-select: none;
      font-size: 0.95em;
      margin-bottom: 6px;
    }
    .toggle-col {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      margin-left: auto;
    }
    .toggle-col.compact {
      align-items: center;
    }
    /* Compact toggle when placed in the right column (prevents it from consuming an extra line) */
    .details-toggle.compact {
      margin: 0;
      font-size: 0.9em;
      white-space: nowrap;
    }
    /* Ensure consistent spacing when details are expanded */
    .details .meta + .md-text,
    .details .meta + .details-text { margin-top: 6px; }

    /* Optional minimap (Leaflet) */
    .map-wrap {
      margin-top: 10px;
      border-radius: var(--smhi-alert-border-radius, 8px);
      overflow: hidden;
      border: 1px solid var(--divider-color);
      background: var(--card-background-color);
      position: relative;
      /* Prevent Leaflet's high z-index panes/controls from escaping above HA dialogs/menus */
      z-index: 0;
      isolation: isolate;
    }
    .geo-map {
      width: 100%;
      aspect-ratio: var(--smhi-alert-map-aspect, 16 / 9);
      height: auto;
      min-height: var(--smhi-alert-map-min-height, 140px);
      max-height: var(--smhi-alert-map-max-height, 260px);
      /* Leaflet attaches panes/controls with high z-index; lock them into this local stacking context */
      position: relative;
      z-index: 0 !important;
    }
    .geo-map.leaflet-container { z-index: 0 !important; }
    /* Keep Leaflet controls above map tiles (but still inside the local stacking context) */
    .geo-map .leaflet-top,
    .geo-map .leaflet-bottom { z-index: 1000 !important; }
    .geo-map .leaflet-control { z-index: 1000 !important; }
    .map-status {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.9em;
      color: var(--secondary-text-color);
      background: color-mix(in srgb, var(--card-background-color) 85%, transparent);
      pointer-events: none;
      opacity: 0;
      transition: opacity 120ms ease;
    }
    .map-status.show {
      opacity: 1;
    }
    /* Keep provider attribution visible and compact. */
    .geo-map .leaflet-control-attribution {
      display: block;
      max-width: calc(100% - 16px);
      margin: 0;
      padding: 2px 6px;
      overflow-wrap: anywhere;
      font-size: 10px;
      line-height: 1.2;
      color: var(--secondary-text-color);
      background: color-mix(in srgb, var(--card-background-color) 94%, transparent);
    }
    .geo-map .leaflet-control-attribution a {
      color: inherit;
      text-decoration: underline;
    }
    .geo-map .leaflet-control-zoom {
      box-shadow: none;
      border: 1px solid var(--divider-color);
      border-radius: 6px;
      overflow: hidden;
      margin: 8px;
    }
    .geo-map .leaflet-control-zoom a {
      background: color-mix(in srgb, var(--card-background-color) 92%, transparent);
      color: var(--primary-text-color);
      border-bottom: 1px solid var(--divider-color);
    }
    .geo-map .leaflet-control-zoom a:last-child { border-bottom: none; }
    .empty {
      color: var(--secondary-text-color);
      padding: 8px var(--smhi-alert-outer-padding, 0px);
    }

    /* Editor-only controls */
    .meta-fields { margin: 12px 0; padding: 0 12px; }
    .meta-row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 8px; padding: 6px 0; }
    .order-actions { display: flex; gap: 6px; }
    .order-btn { background: var(--secondary-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 4px; padding: 2px 6px; cursor: pointer; }
    .order-btn[disabled] { opacity: 0.4; cursor: default; }
    .meta-divider-row { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px; padding: 6px 0; color: var(--secondary-text-color); }
    .meta-divider { border-top: 1px dashed var(--divider-color); height: 0; }
  `;

  constructor() {
    super();
    this._maps = new Map();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    // Rensa timers för att undvika minnesläckor
    clearTimeout(this._holdTimer);
    clearTimeout(this._tapTimer);
    this._clearMaps();
  }

  _clearMaps() {
    for (const [, entry] of this._maps.entries()) {
      try {
        entry?.map?.remove?.();
      } catch (e) {
        // Ignorera fel vid cleanup
      }
    }
    this._maps.clear();
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('You must specify an entity.');
    }
    const normalized = this._normalizeConfig(config);
    const tileConfigChanged = this.config
      && (
        this.config.map_tile_url !== normalized.map_tile_url
        || this.config.map_tile_attribution !== normalized.map_tile_attribution
        || this.config.map_tile_max_zoom !== normalized.map_tile_max_zoom
      );
    if (tileConfigChanged) this._clearMaps();
    this.config = normalized;
    this._expanded = {};
  }

  _mapTileConfig() {
    const customUrl = this.config?.map_tile_url;
    return {
      url: customUrl || OSM_TILE_URL,
      attribution: customUrl ? this.config.map_tile_attribution : OSM_ATTRIBUTION,
      maxZoom: this.config?.map_tile_max_zoom ?? DEFAULT_MAP_TILE_MAX_ZOOM,
    };
  }

  getCardSize() {
    const header = this._showHeader() ? 1 : 0;

    // Important: HA may call getCardSize() before hass is injected.
    // If we return 0 here, Lovelace can drop the card entirely from the editor UI.
    if (!this.hass) return header + 1;

    const messages = this._visibleMessages();
    const count = Array.isArray(messages) ? messages.length : 0;

    // When empty, only reserve a row for the empty message when it is enabled.
    return header + (count > 0 ? count : (this._showEmptyMessage() ? 1 : 0));
  }

  /**
   * Sections (grid) view support.
   * Home Assistant uses this to determine the default/min size and to enable the UI "Layout" tab resizing.
   * Each section is 12 columns wide.
   */
  getGridOptions() {
    // Provide only column sizing. Avoid returning `rows` here so Sections can auto-size height
    // based on content (prevents fixed-height behavior and overlap issues when expanding).
    return {
      columns: 12,
      min_columns: 1,
      max_columns: 12,
      // In edit mode + empty state, HA Sections can collapse cards to 0 height unless a min is provided.
      // This keeps the card selectable/movable even when there is no data.
      min_rows: 1,
    };
  }

  _messages() {
    if (!this.hass || !this.config) return [];
    const stateObj = this.hass.states?.[this.config.entity];
    return stateObj ? stateObj.attributes?.messages || [] : [];
  }

  _visibleMessages() {
    const messages = this._messages();
    if (!Array.isArray(messages)) return [];
    const cfg = this.config || {};
    const filterSev = (cfg.filter_severities || []).map((s) => String(s).toUpperCase());
    const filterAreas = (cfg.filter_areas || []).map((s) => String(s).toLowerCase());

    const filtered = messages.filter((m) => {
      const code = String(m.code || '').toUpperCase();
      const area = String(m.area || '').toLowerCase();
      const sevOk = filterSev.length === 0 || filterSev.includes(code);
      const areaOk = filterAreas.length === 0 || filterAreas.some((x) => area.includes(x));
      return sevOk && areaOk;
    });

    const sorted = [...filtered].sort((a, b) => {
      const order = cfg.sort_order || 'severity_then_time';
      if (order === 'time_desc') {
        const at = new Date(a.start || a.published || 0).getTime();
        const bt = new Date(b.start || b.published || 0).getTime();
        return bt - at;
      }
      // severity_then_time
      const as = this._severityRank(a);
      const bs = this._severityRank(b);
      if (as !== bs) return bs - as; // higher first
      const at = new Date(a.start || a.published || 0).getTime();
      const bt = new Date(b.start || b.published || 0).getTime();
      return bt - at;
    });

    const max = Number(cfg.max_items || 0);
    return max > 0 ? sorted.slice(0, max) : sorted;
  }

  _severityRank(item) {
    const code = String(item?.code || '').toUpperCase();
    switch (code) {
      case 'RED':
        return 4;
      case 'ORANGE':
        return 3;
      case 'YELLOW':
        return 2;
      case 'MESSAGE':
        return 1;
      default:
        return 0;
    }
  }

  _handleIconError(e, fallbackPath) {
    const img = e.target;
    if (img && img.src !== fallbackPath) {
      img.src = fallbackPath;
    }
  }

  _iconTemplate(item) {
    if (item.code === 'MESSAGE') {
      const event = item.event.trim().toLowerCase();
      if (event === 'brandrisk' || event === 'fire risk') {
        return html`<img class="icon" src="${fireIcon}" alt="fire risk" @error=${(e) => this._handleIconError(e, '/local/fire.svg')} />`;
      } else if (event === 'risk för vattenbrist' || event === 'risk for water shortage') {
        return html`<img class="icon" src="${waterShortageIcon}" alt="water shortage" @error=${(e) => this._handleIconError(e, '/local/waterShortage.svg')} />`;
      } else if (event === 'höga temperaturer' || event === 'high temperatures') {
        return html`<img class="icon" src="${temperatureIcon}" alt="high temperatures" @error=${(e) => this._handleIconError(e, '/local/temperature.svg')} />`;
      }
      return html`<ha-icon class="icon" icon="mdi:message-alert-outline" aria-hidden="true"></ha-icon>`;
    }
    switch (item.code) {
      case 'YELLOW':
        return html`<img class="icon" src="${yellowWarningIcon}" alt="yellow warning" @error=${(e) => this._handleIconError(e, '/local/yellowWarning.svg')} />`;
      case 'ORANGE':
        return html`<img class="icon" src="${orangeWarningIcon}" alt="orange warning" @error=${(e) => this._handleIconError(e, '/local/orangeWarning.svg')} />`;
      case 'RED':
        return html`<img class="icon" src="${redWarningIcon}" alt="red warning" @error=${(e) => this._handleIconError(e, '/local/redWarning.svg')} />`;
      default:
        return html`<ha-icon class="icon" icon="mdi:alert-circle-outline" aria-hidden="true"></ha-icon>`;
    }
  }

  render() {
    if (!this.hass || !this.config) return html``;
    const stateObj = this.hass.states?.[this.config.entity];
    const t = this._t.bind(this);
    const messages = this._visibleMessages();

    const header = this._showHeader()
      ? (this.config.title || stateObj?.attributes?.friendly_name || 'SMHI')
      : undefined;

    return html`
      <ha-card .header=${header}>
        ${messages.length === 0
          ? (this._showEmptyMessage()
            ? html`<div class="empty">${t('no_alerts')}</div>`
            : html``)
          : html`<div class="alerts">${this._renderGrouped(messages)}</div>`}
        ${this._renderEditorMetaControls?.() || html``}
      </ha-card>
    `;
  }

  _renderGrouped(messages) {
    const groupBy = this.config?.group_by || 'none';
    if (groupBy === 'none') {
      return messages.map((item, idx) => this._renderAlert(item, idx));
    }
    const groups = {};
    const getKey = (m) => {
      if (groupBy === 'area') return m.area || '—';
      if (groupBy === 'type') return m.event || '—';
      if (groupBy === 'level') return m.level || '—';
      if (groupBy === 'severity') return (m.code || '—');
      return '—';
    };
    for (const m of messages) {
      const key = getKey(m);
      if (!groups[key]) groups[key] = [];
      groups[key].push(m);
    }
    let keys = Object.keys(groups);
    if (groupBy === 'severity') {
      keys.sort((a, b) => {
        const ra = this._severityRank({ code: String(a).toUpperCase() });
        const rb = this._severityRank({ code: String(b).toUpperCase() });
        return rb - ra;
      });
    } else {
      keys.sort((a, b) => String(a).localeCompare(String(b)));
    }
    return keys.map((key) => html`
      <div class="area-group">
        <div class="meta" style="margin: 0;">${key}</div>
        ${groups[key].map((item, idx) => this._renderAlert(item, idx))}
      </div>
    `);
  }

  _splitMetaOrder(rawOrder) {
    const defaultOrder = ['area', 'type', 'level', 'severity', 'published', 'period', 'divider', 'text', 'map'];
    const base = Array.isArray(rawOrder) && rawOrder.length ? rawOrder : defaultOrder;
    // Deduplicate while preserving first occurrence
    let order = base.map((k) => String(k)).filter((k, i, arr) => arr.indexOf(k) === i);
    // Ensure required special keys exist
    if (!order.includes('divider')) order = [...order, 'divider'];
    if (!order.includes('text')) order = [...order, 'text'];
    if (!order.includes('map')) order = [...order, 'map'];
    const dividerIndex = order.indexOf('divider');
    const inlineKeys = dividerIndex >= 0 ? order.slice(0, dividerIndex) : order.filter((k) => k !== 'divider');
    const detailsKeys = dividerIndex >= 0 ? order.slice(dividerIndex + 1) : [];
    return { order, inlineKeys, detailsKeys };
  }

  _renderAlert(item, idx) {
    const t = this._t.bind(this);
    const code = String(item.code || '').toUpperCase();
    const sevClass =
      code === 'RED' ? 'sev-red' : code === 'ORANGE' ? 'sev-orange' : code === 'YELLOW' ? 'sev-yellow' : 'sev-message';
    const sevBgClass = this.config?.severity_background ? 'bg-severity' : '';
    const showIcon = this.config.show_icon !== false;
    const { inlineKeys, detailsKeys } = this._splitMetaOrder(this.config?.meta_order);

    // Default expansion: keep details collapsed unless user expands
    const alertKey = this._alertKey(item, idx);
    const hasStored = Object.prototype.hasOwnProperty.call(this._expanded || {}, alertKey);
    const expanded = hasStored ? !!this._expanded[alertKey] : false;

    const mkTextBlock = () => {
      if (this.config.show_text === false) return null;
      const txt = this._detailsText(item);
      if (!txt) return null;
      return this._formatDetailsText(txt);
    };

    const mkMapBlock = () => {
      if (!this.config?.show_map) return null;
      if (!item?.geometry) return null;
      const mapId = `smhi-alert-map-${this._sanitizeDomId(alertKey)}`;
      const statusId = `smhi-alert-map-status-${this._sanitizeDomId(alertKey)}`;
      return html`
        <div
          class="map-wrap"
          @pointerdown=${(e) => e.stopPropagation()}
          @pointerup=${(e) => e.stopPropagation()}
          @click=${(e) => e.stopPropagation()}
        >
          <div id=${statusId} class="map-status show">${t('map_loading')}</div>
          <div
            id=${mapId}
            class="geo-map"
            data-map-key=${alertKey}
          ></div>
        </div>
      `;
    };

    const metaSpanFor = (key) => {
      if (key === 'area') {
        return (this.config.show_area !== false && item.area)
          ? html`<span><b>${t('area')}:</b> ${item.area}</span>`
          : null;
      }
      if (key === 'type') {
        return (this.config.show_type !== false && item.event)
          ? html`<span><b>${t('type')}:</b> ${item.event}</span>`
          : null;
      }
      if (key === 'level') {
        return (this.config.show_level !== false && item.level)
          ? html`<span><b>${t('level')}:</b> ${item.level}</span>`
          : null;
      }
      if (key === 'severity') {
        return (this.config.show_severity !== false && item.severity)
          ? html`<span><b>${t('severity')}:</b> ${item.severity}</span>`
          : null;
      }
      if (key === 'published') {
        return (this.config.show_published !== false && item.published)
          ? html`<span><b>${t('published')}:</b> ${this._fmtTs(item.published)}</span>`
          : null;
      }
      if (key === 'period') {
        return (this.config.show_period !== false && (item.start || item.end))
          ? html`<span><b>${t('period')}:</b> ${this._fmtTs(item.start)} – ${this._fmtEnd(item.end)}</span>`
          : null;
      }
      return null;
    };

    const buildSectionBlocks = (keys, section) => {
      // Build blocks in order, but group consecutive meta spans into <div class="meta">...</div>
      const blocks = [];
      let metaGroup = [];
      const flushMeta = () => {
        if (metaGroup.length > 0) {
          blocks.push(html`<div class="meta">${metaGroup}</div>`);
          metaGroup = [];
        }
      };

      for (const k of keys) {
        if (k === 'divider') continue;
        if (k === 'text') {
          flushMeta();
          const node = mkTextBlock();
          if (node) blocks.push(section === 'inline' ? html`<div class="details">${node}</div>` : node);
          continue;
        }
        if (k === 'map') {
          // In details section, only render map when expanded (unless user moved map before divider)
          if (section === 'details' && !expanded) {
            flushMeta();
            continue;
          }
          flushMeta();
          const node = mkMapBlock();
          if (node) blocks.push(section === 'inline' ? html`<div class="details">${node}</div>` : node);
          continue;
        }
        const span = metaSpanFor(k);
        if (span) metaGroup.push(span);
      }

      flushMeta();
      return blocks;
    };

    const sectionHasPotentialContent = (keys) => {
      for (const k of keys) {
        if (k === 'divider') continue;
        if (k === 'text') {
          if (this.config.show_text !== false && !!this._detailsText(item)) return true;
          continue;
        }
        if (k === 'map') {
          if (this.config?.show_map && !!item?.geometry) return true;
          continue;
        }
        if (metaSpanFor(k)) return true;
      }
      return false;
    };

    const inlineBlocks = buildSectionBlocks(inlineKeys, 'inline');
    const detailsBlocks = buildSectionBlocks(detailsKeys, 'details');
    const expandable = sectionHasPotentialContent(detailsKeys);
    const isCompact = !expanded && inlineBlocks.length === 0;

    return html`
      <div
        class="alert ${sevClass} ${sevBgClass} ${isCompact ? 'compact' : ''}"
        role="button"
        tabindex="0"
        aria-label="${item.area || ''}"
        @pointerdown=${(e) => this._onPointerDown(e)}
        @pointerup=${(e) => this._onPointerUp(e, item)}
        @keydown=${(e) => this._onKeydown(e, item)}
      >
        ${showIcon ? html`<div class="icon-col ${isCompact ? 'compact' : ''}">${this._iconTemplate(item)}</div>` : html``}
        <div class="content ${isCompact ? 'compact' : ''}">
          <div class="title">
            <div class="district ${isCompact ? 'compact' : ''}">${item.descr || item.area || item.event || ''}</div>
            ${expandable ? html`
              <div class="toggle-col ${isCompact ? 'compact' : ''}">
                <div
                  class="details-toggle compact"
                  role="button"
                  tabindex="0"
                  aria-expanded="${expanded}"
                  title="${expanded ? t('hide_details') : t('show_details')}"
                  @click=${(e) => this._toggleDetails(e, item, idx)}
                  @pointerdown=${(e) => e.stopPropagation()}
                  @pointerup=${(e) => e.stopPropagation()}
                  @keydown=${(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      this._toggleDetails(e, item, idx);
                    }
                    e.stopPropagation();
                  }}
                >
                  ${expanded ? t('hide_details') : t('show_details')}
                </div>
              </div>
            ` : html``}
          </div>
          ${inlineBlocks.length > 0 ? html`${inlineBlocks}` : html``}
          ${expandable
            ? html`
                <div class="details">
                  ${expanded ? html`
                    ${detailsBlocks.length > 0 ? html`${detailsBlocks}` : html``}
                  ` : html``}
                </div>
              `
            : html``}
        </div>
      </div>`;
  }

  _detailsText(item) {
    // Prefer details; fall back to descr; ensure string
    const primary = item?.details;
    const fallback = item?.descr;
    const text = (primary && String(primary).trim().length > 0)
      ? String(primary)
      : (fallback && String(fallback).trim().length > 0)
        ? String(fallback)
        : '';
    return text || '';
  }

  _normalizeMultiline(value) {
    if (!value) return '';
    let text = String(value).replace(/\r\n?/g, '\n');
    // Trim leading/trailing empty lines
    text = text.replace(/^\s*\n/, '').replace(/\n\s*$/, '');
    const lines = text.split('\n');
    // Determine common leading indent among non-empty lines, preferring positive indents.
    // This avoids the first unindented heading line forcing minIndent to 0
    const indents = lines
      .filter((ln) => ln.trim().length > 0)
      .map((ln) => {
        const m = ln.match(/^(\s*)/);
        return m ? m[1].length : 0;
      });
    const positive = indents.filter((n) => n > 0);
    const minIndent = positive.length > 0 ? Math.min(...positive) : (indents.length > 0 ? Math.min(...indents) : 0);
    const deindented = lines.map((ln) => (minIndent > 0 && ln.startsWith(' '.repeat(minIndent)) ? ln.slice(minIndent) : ln));
    return deindented.join('\n');
  }

  _formatDetailsText(raw) {
    const normalized = this._normalizeMultiline(raw);
    if (!normalized) return null;
    const sections = this._parseDetailsSections(normalized);
    const hasHeadings = sections.some((section) => !!section.heading);
    const hasBlankLines = /\n\s*\n/.test(normalized);
    if (!hasHeadings && !hasBlankLines) {
      return html`<div class="md-text">${normalized}</div>`;
    }

    const blocks = sections
      .map((section) => {
        const paragraphs = this._splitParagraphs(section.lines || []);
        if (paragraphs.length === 0 && !section.heading) return null;
        const wantsList = this._headingWantsList(section.heading, paragraphs);
        const body = wantsList
          ? html`<ul class="details-list">${paragraphs.map((p) => html`<li>${p}</li>`)}</ul>`
          : html`${paragraphs.map((p) => html`<p class="details-paragraph">${p}</p>`)}`;
        return html`
          <div class="details-section">
            ${section.heading ? html`<div class="details-heading">${section.heading}</div>` : html``}
            ${body}
          </div>
        `;
      })
      .filter(Boolean);

    return html`<div class="details-text">${blocks}</div>`;
  }

  _parseDetailsSections(text) {
    const lines = String(text).split('\n');
    const sections = [];
    let current = null;

    const pushCurrent = () => {
      if (!current) return;
      const trimmed = this._trimEmptyLines(current.lines || []);
      if (trimmed.length === 0 && !current.heading) {
        current = null;
        return;
      }
      sections.push({ heading: current.heading, lines: trimmed });
      current = null;
    };

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        if (current) current.lines.push('');
        continue;
      }
      const headingMatch = this._matchDetailsHeading(line);
      if (headingMatch) {
        pushCurrent();
        current = { heading: headingMatch.heading, lines: [] };
        if (headingMatch.rest) current.lines.push(headingMatch.rest);
        continue;
      }
      if (!current) current = { heading: null, lines: [] };
      current.lines.push(line);
    }
    pushCurrent();
    return sections;
  }

  _matchDetailsHeading(line) {
    const match = String(line).match(/^([^:]{2,80})\s*:\s*(.*)$/);
    if (!match) return null;
    const heading = match[1].trim();
    if (!heading) return null;
    const rest = (match[2] || '').trim();
    const words = heading.split(/\s+/).filter(Boolean);
    if (heading.length > 50 || words.length > 6) return null;
    if (!/[A-Za-zÅÄÖåäö]/.test(heading)) return null;
    if (/[0-9]/.test(heading) && !heading.includes('?')) return null;
    if (/https?:\/\//i.test(heading)) return null;
    return { heading, rest };
  }

  _trimEmptyLines(lines) {
    let start = 0;
    while (start < lines.length && !lines[start].trim()) start += 1;
    let end = lines.length - 1;
    while (end >= start && !lines[end].trim()) end -= 1;
    return lines.slice(start, end + 1);
  }

  _splitParagraphs(lines) {
    const paragraphs = [];
    let current = [];
    const flush = () => {
      if (current.length === 0) return;
      paragraphs.push(current.join(' ').replace(/\s+/g, ' ').trim());
      current = [];
    };

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        flush();
        continue;
      }
      current.push(trimmed);
    }
    flush();
    return paragraphs;
  }

  _headingWantsList(heading, paragraphs) {
    if (!heading) return false;
    if (!Array.isArray(paragraphs) || paragraphs.length < 2) return false;
    const normalized = heading.trim().toLowerCase();
    return normalized.includes('tänka')
      || normalized.includes('att tänka')
      || normalized.includes('tips')
      || normalized.includes('advice')
      || normalized.includes('recommendation')
      || normalized.includes('what should i');
  }

  _toggleDetails(e, item, idx) {
    e.stopPropagation();
    const key = this._alertKey(item, idx);
    this._expanded = { ...this._expanded, [key]: !this._expanded[key] };
  }

  _onPointerDown(e) {
    if (e.button !== 0) return; // left click only
    clearTimeout(this._holdTimer);
    this._holdFired = false;
    this._holdTimer = setTimeout(() => {
      this._holdFired = true;
      // we don't know item here; handled on pointerup
    }, 500);
  }

  _onPointerUp(e, item) {
    if (e.button !== 0) return;
    clearTimeout(this._holdTimer);
    if (this._holdFired) {
      this._runAction(this.config?.hold_action || this.config?.tap_action || { action: 'more-info' }, item);
      return;
    }
    const now = Date.now();
    if (this._lastTap && now - this._lastTap < 250) {
      this._lastTap = 0;
      this._runAction(this.config?.double_tap_action || this.config?.tap_action || { action: 'more-info' }, item);
    } else {
      this._lastTap = now;
      clearTimeout(this._tapTimer);
      this._tapTimer = setTimeout(() => {
        // if no double tap happened
        if (this._lastTap && Date.now() - this._lastTap >= 250) {
          this._lastTap = 0;
          this._runAction(this.config?.tap_action || { action: 'more-info' }, item);
        }
      }, 260);
    }
  }

  _onKeydown(e, item) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      this._runAction(this.config?.tap_action || { action: 'more-info' }, item);
    }
  }

  _alertKey(item, idx) {
    return `${String(item.code || '')}-${String(item.area || '')}-${String(item.start || item.published || idx)}`;
  }

  _fmtTs(value) {
    return this._formatDate(value);
  }

  _fmtEnd(end) {
    const val = String(end || '').trim().toLowerCase();
    if (!end || val === 'okänt' || val === 'unknown') return this._t('unknown');
    return this._formatDate(end);
  }

  _formatDate(value) {
    if (!value) return '';
    const date = this._parseDate(value);
    if (!date) return String(value);
    const locale = (this.hass?.language || 'en').toLowerCase();
    const format = this.config?.date_format || 'locale';
    if (format === 'weekday_time') {
      return this._formatDateParts(
        date,
        locale,
        { weekday: 'long' },
        { hour: '2-digit', minute: '2-digit' },
      );
    }
    if (format === 'day_month_time') {
      return this._formatDateParts(
        date,
        locale,
        { day: 'numeric', month: 'long' },
        { hour: '2-digit', minute: '2-digit' },
      );
    }
    if (format === 'day_month_time_year') {
      return this._formatDateParts(
        date,
        locale,
        { day: 'numeric', month: 'long', year: 'numeric' },
        { hour: '2-digit', minute: '2-digit' },
      );
    }
    return date.toLocaleString(locale);
  }

  _formatDateParts(date, locale, dateOptions, timeOptions) {
    const safeTimeOptions = timeOptions ? { ...timeOptions } : null;
    if (safeTimeOptions && !Object.prototype.hasOwnProperty.call(safeTimeOptions, 'hour12')) {
      safeTimeOptions.hour12 = false;
    }
    const dateStr = dateOptions
      ? new Intl.DateTimeFormat(locale, dateOptions).format(date)
      : '';
    const timeStr = safeTimeOptions
      ? new Intl.DateTimeFormat(locale, safeTimeOptions).format(date)
      : '';
    if (dateStr && timeStr) return `${dateStr} ${timeStr}`;
    return dateStr || timeStr || '';
  }

  _parseDate(value) {
    if (!value) return null;
    if (value instanceof Date) {
      return Number.isNaN(value.getTime()) ? null : value;
    }
    if (typeof value === 'number') {
      const numericDate = new Date(value);
      return Number.isNaN(numericDate.getTime()) ? null : numericDate;
    }
    const raw = String(value).trim();
    if (!raw) return null;
    let normalized = raw;
    if (/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(raw)) {
      normalized = raw.replace(' ', 'T');
    }
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  _showHeader() {
    return this.config?.show_header !== false;
  }

  _showEmptyMessage() {
    return this.config?.show_empty_message !== false;
  }

  updated() {
    // When geometry maps are enabled, create/update maps for alerts where the map is actually rendered.
    this._maybeInitMaps();
  }

  _maybeInitMaps() {
    if (!this.config?.show_map) return;
    if (!this.renderRoot) return;

    const messages = this._visibleMessages();
    const { inlineKeys, detailsKeys } = this._splitMetaOrder(this.config?.meta_order);
    const mapInInline = inlineKeys.includes('map');
    const mapInDetails = detailsKeys.includes('map');
    const activeKeys = new Set();
    for (let i = 0; i < messages.length; i++) {
      const item = messages[i];
      const key = this._alertKey(item, i);
      const expanded = !!this._expanded?.[key];
      const mapVisible = (mapInInline || (mapInDetails && expanded));
      if (!mapVisible) continue;
      if (!item?.geometry) continue;
      const mapId = `smhi-alert-map-${this._sanitizeDomId(key)}`;
      const el = this.renderRoot.querySelector(`#${mapId}`);
      if (!el) continue;
      activeKeys.add(key);
      this._ensureLeafletAndRenderMap(key, el, item.geometry, String(item.code || '').toUpperCase()).catch(() => {
        const statusEl = this.renderRoot?.querySelector?.(`#smhi-alert-map-status-${this._sanitizeDomId(key)}`);
        if (statusEl) {
          statusEl.textContent = this._t('map_failed');
          statusEl.classList.add('show');
        }
      });
    }

    // Cleanup maps that are no longer rendered (collapsed/filtered away)
    for (const [key, entry] of this._maps.entries()) {
      if (activeKeys.has(key)) continue;
      try {
        entry?.map?.remove?.();
      } catch (e) {}
      this._maps.delete(key);
    }
  }

  _sanitizeDomId(value) {
    // Important: this value is used inside querySelector(`#${id}`).
    // Characters like ':' and '.' make the selector invalid unless escaped, so we strip them here.
    // We already prefix with 'smhi-alert-map-' / 'smhi-alert-map-status-' so the final id starts with a letter.
    return String(value || '').replace(/[^a-zA-Z0-9\-_]/g, '_');
  }

  _severityStyle(code) {
    const c = String(code || '').toUpperCase();
    const accentVar =
      c === 'RED' ? 'var(--smhi-alert-red, var(--error-color, #e74c3c))'
      : c === 'ORANGE' ? 'var(--smhi-alert-orange, #e67e22)'
      : c === 'YELLOW' ? 'var(--smhi-alert-yellow, #f1c40f)'
      : 'var(--smhi-alert-message, var(--primary-color))';
    return {
      color: accentVar,
      fillColor: accentVar,
      weight: 2,
      opacity: 0.9,
      fillOpacity: 0.18,
    };
  }

  _geoSignature(geometry) {
    try {
      if (!geometry || typeof geometry !== 'object') return '';
      const t = geometry.type || '';
      if (t === 'FeatureCollection') return `FC:${(geometry.features || []).length}`;
      if (t === 'Feature') return `F:${geometry.geometry?.type || ''}`;
      if (Array.isArray(geometry.coordinates)) return `${t}:${geometry.coordinates.length}`;
      return String(t);
    } catch (e) {
      return '';
    }
  }

  async _ensureLeafletAndRenderMap(key, containerEl, geometry, code) {
    this._ensureLeafletCssInShadowRoot();
    const statusEl = this.renderRoot?.querySelector?.(`#smhi-alert-map-status-${this._sanitizeDomId(key)}`);
    if (statusEl) {
      statusEl.textContent = this._t('map_loading_leaflet');
      statusEl.classList.add('show');
    }
    const L = await this._ensureLeaflet();
    if (!L) return;

    const sig = `${this._geoSignature(geometry)}|${String(code || '').toUpperCase()}`;
    const existing = this._maps.get(key);
    const containerChanged = existing?.container && existing.container !== containerEl;

    if (existing && containerChanged) {
      try { existing.map.remove(); } catch (e) {}
      this._maps.delete(key);
    }

    let entry = this._maps.get(key);
    if (!entry) {
      const map = L.map(containerEl, {
        zoomControl: this.config?.map_zoom_controls !== false,
        attributionControl: true,
        // Keep wheel zoom off by default so dashboard scroll isn't affected
        scrollWheelZoom: this.config?.map_scroll_wheel === true,
        // Double click zoom is a nice zoom affordance without interfering with page scroll
        doubleClickZoom: true,
        boxZoom: false,
        keyboard: false,
        touchZoom: true,
        tap: false,
      });
      const tileConfig = this._mapTileConfig();
      L.tileLayer(tileConfig.url, {
        maxZoom: tileConfig.maxZoom,
        attribution: tileConfig.attribution,
        referrerPolicy: MAP_TILE_REFERRER_POLICY,
      }).addTo(map);
      entry = { map, layer: null, sig: '', container: containerEl };
      this._maps.set(key, entry);
    }

    if (entry.sig !== sig) {
      if (statusEl) {
        statusEl.textContent = this._t('map_rendering');
        statusEl.classList.add('show');
      }
      try { entry.layer?.remove?.(); } catch (e) {}
      entry.layer = L.geoJSON(geometry, { style: () => this._severityStyle(code) }).addTo(entry.map);
      entry.sig = sig;
      try {
        const bounds = entry.layer.getBounds?.();
        if (bounds && bounds.isValid && bounds.isValid()) {
          entry.map.fitBounds(bounds, { padding: [12, 12] });
        }
      } catch (e) {}
    }

    // When a map is created in a newly rendered/expanded container, Leaflet needs a size invalidate.
    requestAnimationFrame(() => {
      try { entry.map.invalidateSize(); } catch (e) {}
    });

    // Hide loading overlay once we have a map instance.
    if (statusEl) {
      statusEl.classList.remove('show');
      statusEl.textContent = '';
    }
  }

  _ensureLeaflet() {
    // Share one loader promise across all card instances.
    window.__smhiAlertLeafletPromise = window.__smhiAlertLeafletPromise || null;
    if (window.L && window.L.map) return Promise.resolve(window.L);
    if (window.__smhiAlertLeafletPromise) return window.__smhiAlertLeafletPromise;

    // Prefer ESM import (typically CSP-friendlier in HA than injecting <script src=...>).
    window.__smhiAlertLeafletPromise = (async () => {
      try {
        const mod = await this._withTimeout(import(LEAFLET_ESM_URL), 12000, 'Leaflet ESM import timed out');
        const L = mod?.default || mod?.L || mod;
        if (L && L.map) {
          // Also set window.L for any downstream libs expecting the global.
          window.L = window.L || L;
          return L;
        }
        throw new Error('Leaflet ESM loaded but did not expose L.map');
      } catch (err) {
        // Fallback to classic script tag (may still be blocked by CSP).
        const jsId = 'smhi-alert-leaflet-js';
        return await new Promise((resolve, reject) => {
          try {
            if (window.L && window.L.map) {
              resolve(window.L);
              return;
            }
            let script = document.getElementById(jsId);
            if (!script) {
              script = document.createElement('script');
              script.id = jsId;
              script.src = LEAFLET_JS_SRC;
              script.async = true;
              document.head.appendChild(script);
            }
            script.addEventListener('load', () => resolve(window.L));
            script.addEventListener('error', () => reject(err || new Error('Failed to load Leaflet')));
          } catch (e) {
            reject(err || e);
          }
        });
      }
    })();

    return window.__smhiAlertLeafletPromise;
  }

  _withTimeout(promise, ms, message) {
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error(message || 'Timed out')), ms);
      promise.then((v) => { clearTimeout(t); resolve(v); }).catch((e) => { clearTimeout(t); reject(e); });
    });
  }

  _ensureLeafletCssInShadowRoot() {
    const id = 'smhi-alert-leaflet-css-shadow';
    try {
      if (!this.renderRoot) return;
      if (this.renderRoot.querySelector(`#${id}`)) return;
      const link = document.createElement('link');
      link.id = id;
      link.rel = 'stylesheet';
      link.href = LEAFLET_CSS_HREF;
      this.renderRoot.appendChild(link);
    } catch (e) {
      // ignore
    }
  }

  shouldUpdate(changed) {
    if (changed.has('config')) return true;
    if (changed.has('hass')) {
      const stateObj = this.hass.states?.[this.config.entity];
      const lastUpdate = String(stateObj?.attributes?.last_update || '');
      const messages = stateObj?.attributes?.messages || [];
      // Include details/descr to re-render when description text changes
      const msgKey = JSON.stringify(messages?.map((m) => [m.code, m.area, m.start, m.published, m.details, m.descr]));
      const combinedKey = `${lastUpdate}|${msgKey}|${this.hass.language}`;
      if (this._lastKey !== combinedKey) {
        this._lastKey = combinedKey;
        return true;
      }
      return false;
    }
    return true;
  }

  _t(key) {
    const lang = (this.hass?.language || 'en').toLowerCase().split('-')[0];
    const dict = {
      en: {
        no_alerts: 'No alerts',
        area: 'Area',
        type: 'Type',
        level: 'Level',
        severity: 'Severity',
        published: 'Published',
        period: 'Period',
        // description_short kept for backward compat but unused
        description_short: 'Descr',
        show_details: 'Show details',
        hide_details: 'Hide details',
        unknown: 'Unknown',
        map_loading: 'Loading map…',
        map_loading_leaflet: 'Loading map (Leaflet)…',
        map_rendering: 'Rendering area…',
        map_failed: 'Map failed to load (blocked by browser/HA CSP)',
      },
      sv: {
        no_alerts: 'Inga varningar',
        area: 'Område',
        type: 'Typ',
        level: 'Nivå',
        severity: 'Allvarlighetsgrad',
        published: 'Publicerad',
        period: 'Period',
        // description_short kept for backward compat but unused
        description_short: 'Beskrivning',
        show_details: 'Visa detaljer',
        hide_details: 'Dölj detaljer',
        unknown: 'Okänt',
        map_loading: 'Laddar karta…',
        map_loading_leaflet: 'Laddar karta (Leaflet)…',
        map_rendering: 'Ritar område…',
        map_failed: 'Kartan kunde inte laddas (blockerad av webbläsare/HA CSP)',
      },
    };
    return (dict[lang] || dict.en)[key] || key;
  }

  _normalizeConfig(config) {
    const normalized = { ...config };
    // Backwards compatibility mappings
    if (normalized.show_text === undefined && normalized.show_details !== undefined) {
      normalized.show_text = normalized.show_details;
    }
    // Defaults
    if (normalized.show_header === undefined) normalized.show_header = true;
    if (normalized.show_empty_message === undefined) normalized.show_empty_message = true;
    if (normalized.show_area === undefined) normalized.show_area = true;
    if (normalized.show_type === undefined) normalized.show_type = true;
    if (normalized.show_level === undefined) normalized.show_level = true;
    if (normalized.show_severity === undefined) normalized.show_severity = true;
    if (normalized.show_published === undefined) normalized.show_published = true;
    if (normalized.show_period === undefined) normalized.show_period = true;
    if (normalized.show_text === undefined) normalized.show_text = true;
    if (normalized.show_icon === undefined) normalized.show_icon = true;
    if (normalized.severity_background === undefined) normalized.severity_background = false;
    if (normalized.show_map === undefined) normalized.show_map = false;
    if (normalized.map_zoom_controls === undefined) normalized.map_zoom_controls = true;
    if (normalized.map_scroll_wheel === undefined) normalized.map_scroll_wheel = false;
    normalizeMapTileConfig(normalized);
    if (normalized.max_items === undefined) normalized.max_items = 0;
    if (normalized.sort_order === undefined) normalized.sort_order = 'severity_then_time';
    if (normalized.date_format === undefined) normalized.date_format = 'locale';
    if (normalized.group_by === undefined) normalized.group_by = 'none';
    const allowedDateFormats = ['locale', 'day_month_time', 'weekday_time', 'day_month_time_year'];
    if (!allowedDateFormats.includes(normalized.date_format)) {
      normalized.date_format = 'locale';
    }
    if (!Array.isArray(normalized.meta_order) || normalized.meta_order.length === 0) {
      // Default to placing text + map in the details section (after divider)
      normalized.meta_order = ['area','type','level','severity','published','period','divider','text','map'];
    } else {
      // Ensure divider/text/map exist
      if (!normalized.meta_order.includes('divider')) normalized.meta_order = [...normalized.meta_order, 'divider'];
      if (!normalized.meta_order.includes('text')) normalized.meta_order = [...normalized.meta_order, 'text'];
      if (!normalized.meta_order.includes('map')) normalized.meta_order = [...normalized.meta_order, 'map'];
    }
    if (!Array.isArray(normalized.filter_severities)) normalized.filter_severities = [];
    if (!Array.isArray(normalized.filter_areas)) normalized.filter_areas = [];
    // collapse_details is no longer used; collapse is inferred by divider position
    delete normalized.collapse_details;
    if (Object.prototype.hasOwnProperty.call(normalized, 'hide_when_empty')) delete normalized.hide_when_empty;
    if (Object.prototype.hasOwnProperty.call(normalized, 'debug')) delete normalized.debug; // legacy
    // `map_height` is deprecated (map is now responsive). Ignore saved configs that still include it.
    if (Object.prototype.hasOwnProperty.call(normalized, 'map_height')) delete normalized.map_height;
    if (Object.prototype.hasOwnProperty.call(normalized, 'map_zoom')) delete normalized.map_zoom; // legacy
    if (normalized.show_border === undefined) normalized.show_border = true; // kept for compat but unused
    return normalized;
  }

  static getConfigElement() {
    return document.createElement('smhi-alert-card-editor');
  }

  static getStubConfig(hass, entities) {
    return {
      entity: entities.find((e) => e.startsWith('sensor.')) || '',
      title: '',
      show_header: true,
      show_empty_message: true,
      show_icon: true,
      severity_background: false,
      show_map: false,
      map_zoom_controls: true,
      map_scroll_wheel: false,
      map_tile_url: '',
      map_tile_attribution: '',
      map_tile_max_zoom: DEFAULT_MAP_TILE_MAX_ZOOM,
      show_area: true,
      show_type: true,
      show_level: true,
      show_severity: true,
      show_published: true,
      show_period: true,
      show_text: true,
      max_items: 0,
      sort_order: 'severity_then_time',
      date_format: 'locale',
      group_by: 'none',
      filter_severities: [],
      filter_areas: [],
      // collapse inferred by divider; default puts text in details (after divider)
      meta_order: ['area','type','level','severity','published','period','divider','text','map'],
    };
  }
}

if (!customElements.get('smhi-alert-card')) {
  customElements.define('smhi-alert-card', SmhiAlertCard);
}

class SmhiAlertCardEditor extends LitElement {
  static properties = {
    hass: {},
    _config: {},
  };

  static styles = css`
    .container { padding: 8px 0 0 0; }
    .map-hint { margin: 10px 0 12px 0; padding: 0 12px; }
    .map-hint .hint-title { font-weight: 600; margin-bottom: 4px; }
    .map-hint .hint-text { color: var(--secondary-text-color); font-size: 0.95em; line-height: 1.4; }
    .meta-fields { margin: 12px 0; padding: 8px 12px; }
    .meta-fields-title { color: var(--secondary-text-color); margin-bottom: 6px; }
    .meta-row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 8px; padding: 6px 0; }
    .order-actions { display: flex; gap: 6px; }
  `;

  setConfig(config) {
    this._config = config;
  }

  render() {
    if (!this.hass || !this._config) return html``;
    const lang = (this.hass?.language || 'en').toLowerCase();
    const dateFormatOptions = lang.startsWith('sv')
      ? [
          { value: 'locale', label: 'Systemstandard' },
          { value: 'day_month_time', label: '14 januari 13:00' },
          { value: 'weekday_time', label: 'Onsdag 13:00' },
          { value: 'day_month_time_year', label: '14 januari 2026 13:00' },
        ]
      : [
          { value: 'locale', label: 'System default' },
          { value: 'day_month_time', label: '14 January 13:00' },
          { value: 'weekday_time', label: 'Wednesday 13:00' },
          { value: 'day_month_time_year', label: '14 January 2026 13:00' },
        ];
    const dateFormatLabel = lang.startsWith('sv') ? 'Datumformat' : 'Date format';
    const schema = [
      { name: 'entity', label: 'Entity', required: true, selector: { entity: { domain: 'sensor' } } },
      { name: 'title', label: 'Title', selector: { text: {} } },
      { name: 'show_header', label: 'Show header', selector: { boolean: {} } },
      { name: 'show_empty_message', label: 'Show empty message', selector: { boolean: {} } },
      { name: 'show_icon', label: 'Show icon', selector: { boolean: {} } },
      { name: 'severity_background', label: 'Severity background', selector: { boolean: {} } },
      { name: 'show_map', label: 'Show map (geometry)', selector: { boolean: {} } },
      { name: 'map_zoom_controls', label: 'Map zoom controls (+/−)', selector: { boolean: {} } },
      { name: 'map_scroll_wheel', label: 'Map scroll wheel zoom', selector: { boolean: {} } },
      { name: 'map_tile_url', label: 'Custom map tile URL', selector: { text: {} } },
      { name: 'map_tile_attribution', label: 'Custom map tile attribution', selector: { text: {} } },
      { name: 'map_tile_max_zoom', label: 'Map tile maximum zoom', selector: { number: { min: 0, max: MAX_MAP_TILE_MAX_ZOOM, mode: 'box' } } },
      { name: 'max_items', label: 'Max items', selector: { number: { min: 0, mode: 'box' } } },
      {
        name: 'sort_order', label: 'Sort order',
        selector: { select: { mode: 'dropdown', options: [
          { value: 'severity_then_time', label: 'Severity then time' },
          { value: 'time_desc', label: 'Time (newest first)' },
        ] } },
      },
      { name: 'date_format', label: dateFormatLabel, selector: { select: { mode: 'dropdown', options: dateFormatOptions } } },
      { name: 'group_by', label: 'Group by', selector: { select: { mode: 'dropdown', options: [
        { value: 'none', label: 'No grouping' },
        { value: 'area', label: 'By area' },
        { value: 'type', label: 'By type' },
        { value: 'level', label: 'By level' },
        { value: 'severity', label: 'By severity' },
      ] } } },
      { name: 'filter_severities', label: 'Filter severities', selector: { select: { multiple: true, options: [
        { value: 'RED', label: 'RED' },
        { value: 'ORANGE', label: 'ORANGE' },
        { value: 'YELLOW', label: 'YELLOW' },
        { value: 'MESSAGE', label: 'MESSAGE' },
      ] } } },
      { name: 'filter_areas', label: 'Filter areas (comma-separated)', selector: { text: {} } },
      // No explicit collapse or show_text; details are inferred by divider & per-meta toggles
      // actions (use ui_action selector for full UI in editor)
      { name: 'tap_action', label: 'Tap action', selector: { ui_action: {} } },
      { name: 'double_tap_action', label: 'Double tap action', selector: { ui_action: {} } },
      { name: 'hold_action', label: 'Hold action', selector: { ui_action: {} } },
    ];

    const data = {
      entity: this._config.entity || '',
      title: this._config.title || '',
      show_header: this._config.show_header !== undefined ? this._config.show_header : true,
      show_empty_message: this._config.show_empty_message !== undefined ? this._config.show_empty_message : true,
      show_icon: this._config.show_icon !== undefined ? this._config.show_icon : true,
      severity_background: this._config.severity_background !== undefined ? this._config.severity_background : false,
      show_map: this._config.show_map !== undefined ? this._config.show_map : false,
      map_zoom_controls: this._config.map_zoom_controls !== undefined ? this._config.map_zoom_controls : true,
      map_scroll_wheel: this._config.map_scroll_wheel !== undefined ? this._config.map_scroll_wheel : false,
      map_tile_url: this._config.map_tile_url || '',
      map_tile_attribution: this._config.map_tile_attribution || '',
      map_tile_max_zoom: this._config.map_tile_max_zoom ?? DEFAULT_MAP_TILE_MAX_ZOOM,
      max_items: this._config.max_items ?? 0,
      sort_order: this._config.sort_order || 'severity_then_time',
      date_format: this._config.date_format || 'locale',
      group_by: this._config.group_by || 'none',
      filter_severities: this._config.filter_severities || [],
      filter_areas: (this._config.filter_areas || []).join(', '),
      // collapse inferred by divider
      show_area: this._config.show_area !== undefined ? this._config.show_area : true,
      show_type: this._config.show_type !== undefined ? this._config.show_type : true,
      show_level: this._config.show_level !== undefined ? this._config.show_level : true,
      show_severity: this._config.show_severity !== undefined ? this._config.show_severity : true,
      show_published: this._config.show_published !== undefined ? this._config.show_published : true,
      show_period: this._config.show_period !== undefined ? this._config.show_period : true,
      show_text: this._config.show_text !== undefined ? this._config.show_text : (this._config.show_details !== undefined ? this._config.show_details : true),
      tap_action: this._config.tap_action || {},
      double_tap_action: this._config.double_tap_action || {},
      hold_action: this._config.hold_action || {},
    };

    const allowed = ['area','type','level','severity','published','period','map'];
    const special = ['divider','text'];
    const allowedWithSpecial = [...allowed, ...special];
    const currentOrderRaw = (this._config.meta_order && Array.isArray(this._config.meta_order) && this._config.meta_order.length)
      ? this._config.meta_order.filter((k) => allowedWithSpecial.includes(k))
      : ['area','type','level','severity','published','period','divider','text','map'];
    // ensure presence
    let currentOrder = [...currentOrderRaw];
    if (!currentOrder.includes('divider')) currentOrder.push('divider');
    if (!currentOrder.includes('text')) currentOrder.push('text');
    if (!currentOrder.includes('map')) currentOrder.push('map');
    const filledOrder = [...currentOrder, ...allowedWithSpecial.filter((k) => !currentOrder.includes(k))];

    const schemaTop = schema.filter((s) => !['tap_action','double_tap_action','hold_action'].includes(s.name));
    const schemaActions = schema.filter((s) => ['tap_action','double_tap_action','hold_action'].includes(s.name));

    const mapHint = {
      title: 'Note: Requires an integration setting',
      text: 'For “Show map (geometry)” to work, enable “Include geometry (map polygons)” in the SMHI Alerts integration (Settings → Devices & Services → SMHI Alerts → Configure).',
    };

    // Keep original schema order, but insert the hint directly below "show_map"
    // by splitting the form at that exact point.
    const showMapIdx = schemaTop.findIndex((s) => s.name === 'show_map');
    const schemaBeforeShowMap = showMapIdx >= 0 ? schemaTop.slice(0, showMapIdx) : schemaTop;
    const schemaShowMapOnly = showMapIdx >= 0 ? schemaTop.slice(showMapIdx, showMapIdx + 1) : [];
    const schemaAfterShowMap = showMapIdx >= 0 ? schemaTop.slice(showMapIdx + 1) : [];

    return html`
      <div class="container">
        <ha-form
          .hass=${this.hass}
          .data=${data}
          .schema=${schemaBeforeShowMap}
          .computeLabel=${this._computeLabel}
          @value-changed=${this._valueChanged}
        ></ha-form>
        ${schemaShowMapOnly.length
          ? html`
              <ha-form
                .hass=${this.hass}
                .data=${data}
                .schema=${schemaShowMapOnly}
                .computeLabel=${this._computeLabel}
                @value-changed=${this._valueChanged}
              ></ha-form>
            `
          : html``}
        ${data.show_map
          ? html`
              <div class="map-hint">
                <div class="hint-title">${mapHint.title}</div>
                <div class="hint-text">${mapHint.text}</div>
              </div>
            `
          : html``}
        ${schemaAfterShowMap.length
          ? html`
              <ha-form
                .hass=${this.hass}
                .data=${data}
                .schema=${schemaAfterShowMap}
                .computeLabel=${this._computeLabel}
                @value-changed=${this._valueChanged}
              ></ha-form>
            `
          : html``}
        <div class="meta-fields">
          ${filledOrder.map((key, index) => {
            if (key === 'divider') {
              return html`
                <ha-settings-row class="meta-divider-row">
                  <span slot="heading">Details divider</span>
                  <div class="order-actions">
                    <mwc-icon-button @click=${() => this._moveMeta(key, -1)} .disabled=${index === 0} aria-label="Move up">
                      <ha-icon icon="mdi:chevron-up"></ha-icon>
                    </mwc-icon-button>
                    <mwc-icon-button @click=${() => this._moveMeta(key, 1)} .disabled=${index === filledOrder.length - 1} aria-label="Move down">
                      <ha-icon icon="mdi:chevron-down"></ha-icon>
                    </mwc-icon-button>
                  </div>
                </ha-settings-row>
              `;
            }
            return html`
              <ha-settings-row class="meta-row">
                <span slot="heading">${this._labelForMeta(key)}</span>
                <span slot="description"></span>
                <div class="order-actions">
                  <mwc-icon-button @click=${() => this._moveMeta(key, -1)} .disabled=${index === 0} aria-label="Move up">
                    <ha-icon icon="mdi:chevron-up"></ha-icon>
                  </mwc-icon-button>
                  <mwc-icon-button @click=${() => this._moveMeta(key, 1)} .disabled=${index === filledOrder.length - 1} aria-label="Move down">
                    <ha-icon icon="mdi:chevron-down"></ha-icon>
                  </mwc-icon-button>
                </div>
                <ha-switch
                  .checked=${this._isMetaShown(key)}
                  @change=${(e) => this._toggleMeta(key, e)}
                ></ha-switch>
              </ha-settings-row>`;
          })}
        </div>
        <ha-form
          .hass=${this.hass}
          .data=${data}
          .schema=${schemaActions}
          .computeLabel=${this._computeLabel}
          @value-changed=${this._valueChanged}
        ></ha-form>
      </div>
    `;
  }

  _valueChanged = (ev) => {
    if (!this._config || !this.hass) return;
    const value = ev.detail?.value || {};
    const next = { ...this._config, ...value };
    // normalize filter_areas from comma-separated string
    if (typeof next.filter_areas === 'string') {
      next.filter_areas = next.filter_areas
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    }
    this._config = next;
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: next } }));
  };

  _isMetaShown(key) {
    if (key === 'area') return this._config.show_area !== false;
    if (key === 'type') return this._config.show_type !== false;
    if (key === 'level') return this._config.show_level !== false;
    if (key === 'severity') return this._config.show_severity !== false;
    if (key === 'published') return this._config.show_published !== false;
    if (key === 'period') return this._config.show_period !== false;
    if (key === 'text') return this._config.show_text !== false;
    if (key === 'map') return this._config.show_map === true;
    if (key === 'divider') return true;
    return true;
  }

  _toggleMeta(key, ev) {
    const on = ev?.target?.checked ?? true;
    let next = { ...this._config };
    if (key === 'area') next.show_area = on;
    else if (key === 'type') next.show_type = on;
    else if (key === 'level') next.show_level = on;
    else if (key === 'severity') next.show_severity = on;
    else if (key === 'published') next.show_published = on;
    else if (key === 'period') next.show_period = on;
    else if (key === 'text') next.show_text = on;
    else if (key === 'map') next.show_map = on;
    this._config = next;
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: next } }));
  }

  _moveMeta(key, delta) {
    // Normalize to the same order the UI renders (includes 'divider' and 'text' and all allowed keys),
    // so moving across the divider is always possible and saved back stably.
    const baseKeys = ['area','type','level','severity','published','period','map'];
    const specialKeys = ['divider','text'];
    const allKeys = [...baseKeys, ...specialKeys];
    const raw = (this._config.meta_order && Array.isArray(this._config.meta_order) && this._config.meta_order.length)
      ? this._config.meta_order.filter((k) => allKeys.includes(k))
      : [...allKeys];
    // Deduplicate while preserving first occurrence
    let current = raw.filter((k, i) => raw.indexOf(k) === i);
    // Ensure presence of divider/text
    if (!current.includes('divider')) current.push('divider');
    if (!current.includes('text')) current.push('text');
    // Ensure all allowed keys are present so their relative order is explicit
    const filled = [...current, ...allKeys.filter((k) => !current.includes(k))];

    const idx = filled.indexOf(key);
    if (idx < 0) return;
    const newIdx = Math.max(0, Math.min(filled.length - 1, idx + delta));
    if (newIdx === idx) return;
    const next = [...filled];
    next.splice(idx, 1);
    next.splice(newIdx, 0, key);
    this._config = { ...this._config, meta_order: next };
    this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config } }));
  }

  _labelForMeta(key) {
    const map = { area: 'Area', type: 'Type', level: 'Level', severity: 'Severity', published: 'Published', period: 'Period', text: 'Text', map: 'Map', divider: '— Details —' };
    return map[key] || key;
  }

  _computeLabel = (schema) => {
    if (schema.label) return schema.label;
    const labels = {
      entity: 'Entity',
      title: 'Title',
      show_header: 'Show header',
      show_empty_message: 'Show empty message',
      show_icon: 'Show icon',
      severity_background: 'Severity background',
      show_map: 'Show map (geometry)',
      map_zoom_controls: 'Map zoom controls (+/−)',
      map_scroll_wheel: 'Map scroll wheel zoom',
      map_tile_url: 'Custom map tile URL',
      map_tile_attribution: 'Custom map tile attribution',
      map_tile_max_zoom: 'Map tile maximum zoom',
      max_items: 'Max items',
      sort_order: 'Sort order',
      date_format: 'Date format',
      group_by: 'Group by',
      filter_severities: 'Filter severities',
      filter_areas: 'Filter areas (comma-separated)',
       // collapse_details removed
      show_area: 'Show area',
      show_type: 'Show type',
      show_level: 'Show level',
      show_severity: 'Show severity',
      show_published: 'Show published',
      show_period: 'Show period',
       // show_text is controlled as a meta toggle, not a top-level control
      tap_action: 'Tap action',
      double_tap_action: 'Double tap action',
      hold_action: 'Hold action',
    };
    return labels[schema.name] || schema.name;
  };
}

if (!customElements.get('smhi-alert-card-editor')) {
  customElements.define('smhi-alert-card-editor', SmhiAlertCardEditor);
}


// Seven card types share this resource; forecast cards do not depend on a warning entity.
const FORECAST_TEXT = {
  en: {
        weather_unknown: "No data",
        weather_next_time: "Next forecast time",
        weather_time: "Forecast time",
        weather_forecast: "Forecast times · Next 48 hours",
        weather_created: "Created",
        wind_title: "Wind gusts",
        wind_caption: "Local SMHI wind gust forecast at the stated times.",
        wind_gust: "Wind gust",
        wind_maximum: "Highest forecast value · Next 24 hours",
        wind_window_end: "Window ends",
        wind_unavailable: "Wind gust forecast is unavailable",
        wind_setup: "Enable local wind gust forecasts in SMHI Alerts, then select a wind gust sensor.",
        precipitation_title: "Precipitation",
        precipitation_caption: "Local SMHI forecast. Amounts are water equivalent totals for each stated interval.",
        precipitation_period: "Forecast interval",
        precipitation_interval_unknown: "Interval not available",
        precipitation_probability: "Chance of at least 0.1 mm",
        precipitation_amount: "Amount in interval",
        precipitation_probability_short: "Chance",
        precipitation_amount_short: "Amount",
        precipitation_unavailable: "Precipitation forecast is unavailable",
        precipitation_setup: "Enable local precipitation forecasts in SMHI Alerts, then select a precipitation sensor.",
        analysis_title: "Weather analysis",
        analysis_caption: "Local MESAN analysis of the past hour. Snow change describes the change in snow amount.",
        analysis_period: "Analysed interval · 1 hour",
        analysis_precipitation: "Precipitation · Past hour",
        analysis_snow_change: "Snow amount change · Past hour",
        analysis_precipitation_short: "Precipitation",
        analysis_snow_change_short: "Snow change",
        analysis_history: "Analysis history · Past 24 hours",
        analysis_unavailable: "Weather analysis is unavailable",
        analysis_setup: "Enable local weather analysis in SMHI Alerts, then select an analysis sensor.",
        analysis_show_history: "Show history",
        analysis_expand_history: "Expand history by default",
        snow_depth_entity: 'Snow depth sensor (optional)',
        snow_depth_title: 'Measured snow depth',
        snow_depth_station: 'Station',
        snow_depth_station_unknown: 'Station not available',
        snow_depth_observed: 'Observed',
        snow_depth_quality: 'Quality',
        snow_depth_quality_g: 'Checked and approved',
        snow_depth_quality_y: 'Unchecked or suspect',
        snow_depth_quality_unknown: 'Quality unknown',
        snow_depth_trace: 'Less than 0.5 cm of snow',
        snow_depth_patchy: 'Patchy snow cover',
        snow_depth_unknown: 'No depth measurement',
        snow_depth_unavailable: 'Snow depth is unavailable',
        snow_depth_stale: 'Snow depth observation is out of date',
        winter_title: 'Winter weather',
        winter_caption: 'Local SMHI forecast for the selected point and stated time.',
        winter_next_time: 'Next forecast time',
        winter_forecast: 'Forecast times · Next 48 hours',
        winter_time: 'Time and precipitation',
        winter_probability: 'Frozen precipitation probability',
        winter_probability_short: 'Frozen',
        winter_temperature: 'Temperature',
        winter_temperature_short: 'Temp.',
        winter_created: 'Created',
        winter_unknown: 'No data',
        winter_unavailable: 'Winter weather is unavailable',
        winter_none: 'No precipitation',
        winter_rain: 'Rain',
        winter_thunderstorm: 'Thunderstorm',
        winter_freezing_rain: 'Freezing rain',
        winter_mixed_ice: 'Mixed / ice',
        winter_snow: 'Snow',
        winter_wet_snow: 'Wet snow',
        winter_rain_snow: 'Rain and snow',
        winter_ice_pellets: 'Ice pellets',
        winter_graupel: 'Graupel',
        winter_hail: 'Hail',
        winter_drizzle: 'Drizzle',
        winter_freezing_drizzle: 'Freezing drizzle',
        winter_setup: 'Enable local winter weather in SMHI Alerts, then select a winter weather sensor.',
        thunder_title: 'Thunderstorm probability',
        thunder_caption: 'Local SMHI forecast for each stated time.',
        thunder_next_time: 'Next forecast time',
        thunder_forecast: 'Forecast times · Next 48 hours',
        thunder_time: 'Forecast time',
        thunder_probability: 'Probability',
        thunder_created: 'Created',
        thunder_unknown: 'No data',
        thunder_unavailable: 'Thunderstorm probability is unavailable',
        fire_title: 'Local fire risk',
        fire_caption: 'Forecast for the selected point · Today. Fire restrictions are issued separately.',
        fire_forest_fire_risk: 'Forest',
        fire_grass_fire_risk: 'Grass',
        fire_forest_dryness: 'Fuel dryness',
        fire_forecast: 'Coming days',
        fire_day: 'Day',
        fire_updated: 'Updated',
        fire_unavailable: 'Today’s fire risk is unavailable',
        fire_unknown: 'No data',
        fire_forest_fire_risk_very_low: 'Very low',
        fire_forest_fire_risk_low: 'Low',
        fire_forest_fire_risk_moderate: 'Moderate',
        fire_forest_fire_risk_high: 'High',
        fire_forest_fire_risk_very_high: 'Very high',
        fire_forest_fire_risk_extreme: 'Extreme',
        fire_grass_fire_risk_snow_covered: 'Snow covered',
        fire_grass_fire_risk_season_over: 'Season over',
        fire_grass_fire_risk_low: 'Low',
        fire_grass_fire_risk_moderate: 'Moderate',
        fire_grass_fire_risk_high: 'High',
        fire_grass_fire_risk_very_high: 'Very high',
        fire_forest_dryness_very_wet: 'Very wet',
        fire_forest_dryness_wet: 'Wet',
        fire_forest_dryness_moderately_wet: 'Moderately wet',
        fire_forest_dryness_dry: 'Dry',
        fire_forest_dryness_very_dry: 'Very dry',
        fire_forest_dryness_extremely_dry: 'Extremely dry',

    entity: 'Sensor', title: 'Title', show_forecast: 'Show forecast',
    forecast_expanded: 'Expand forecast by default',
    fire_setup: 'Enable local fire risk forecasts in SMHI Alerts, then select a fire risk sensor.',
    thunder_setup: 'Enable local thunderstorm probability in SMHI Alerts, then select its sensor.',
  },
  sv: {
        weather_unknown: "Data saknas",
        weather_next_time: "Nästa prognostid",
        weather_time: "Prognostid",
        weather_forecast: "Prognostider · Nästa 48 timmar",
        weather_created: "Skapad",
        wind_title: "Vindbyar",
        wind_caption: "Lokal SMHI-prognos för vindbyar vid angivna tider.",
        wind_gust: "Vindby",
        wind_maximum: "Högsta prognosvärde · Nästa 24 timmar",
        wind_window_end: "Perioden slutar",
        wind_unavailable: "Vindbyprognosen är inte tillgänglig",
        wind_setup: "Aktivera lokala vindbyprognoser i SMHI Alerts och välj sedan en vindbysensor.",
        precipitation_title: "Nederbörd",
        precipitation_caption: "Lokal SMHI-prognos. Mängden är vattenekvivalent nederbörd för hela det angivna intervallet.",
        precipitation_period: "Prognosintervall",
        precipitation_interval_unknown: "Intervallet saknas",
        precipitation_probability: "Sannolikhet för minst 0,1 mm",
        precipitation_amount: "Mängd i intervallet",
        precipitation_probability_short: "Sannolikhet",
        precipitation_amount_short: "Mängd",
        precipitation_unavailable: "Nederbördsprognosen är inte tillgänglig",
        precipitation_setup: "Aktivera lokal nederbördsprognos i SMHI Alerts och välj sedan en nederbördssensor.",
        analysis_title: "Väderanalys",
        analysis_caption: "Lokal MESAN-analys av den senaste timmen. Snöförändring beskriver förändringen av snömängden.",
        analysis_period: "Analyserat intervall · 1 timme",
        analysis_precipitation: "Nederbörd · Senaste timmen",
        analysis_snow_change: "Snömängdens förändring · Senaste timmen",
        analysis_precipitation_short: "Nederbörd",
        analysis_snow_change_short: "Snöförändring",
        analysis_history: "Analyshistorik · Senaste 24 timmarna",
        analysis_unavailable: "Väderanalysen är inte tillgänglig",
        analysis_setup: "Aktivera lokal väderanalys i SMHI Alerts och välj sedan en analyssensor.",
        analysis_show_history: "Visa historik",
        analysis_expand_history: "Visa historiken utfälld från början",
        snow_depth_entity: 'Snödjupssensor (valfri)',
        snow_depth_title: 'Uppmätt snödjup',
        snow_depth_station: 'Station',
        snow_depth_station_unknown: 'Station saknas',
        snow_depth_observed: 'Uppmätt',
        snow_depth_quality: 'Kvalitet',
        snow_depth_quality_g: 'Kontrollerat och godkänt',
        snow_depth_quality_y: 'Okontrollerat eller misstänkt',
        snow_depth_quality_unknown: 'Okänd kvalitet',
        snow_depth_trace: 'Mindre än 0,5 cm snö',
        snow_depth_patchy: 'Fläckvis snötäckt mark',
        snow_depth_unknown: 'Snödjupsvärde saknas',
        snow_depth_unavailable: 'Snödjup är inte tillgängligt',
        snow_depth_stale: 'Snödjupsmätningen är inaktuell',
        winter_title: 'Vinterväder',
        winter_caption: 'Lokal SMHI-prognos för vald punkt vid angiven tid.',
        winter_next_time: 'Nästa prognostid',
        winter_forecast: 'Prognostider · Nästa 48 timmar',
        winter_time: 'Tid och nederbörd',
        winter_probability: 'Sannolikhet för frusen nederbörd',
        winter_probability_short: 'Frusen',
        winter_temperature: 'Temperatur',
        winter_temperature_short: 'Temp.',
        winter_created: 'Skapad',
        winter_unknown: 'Data saknas',
        winter_unavailable: 'Vinterväder är inte tillgängligt',
        winter_none: 'Ingen nederbörd',
        winter_rain: 'Regn',
        winter_thunderstorm: 'Åska',
        winter_freezing_rain: 'Underkylt regn',
        winter_mixed_ice: 'Blandat / is',
        winter_snow: 'Snö',
        winter_wet_snow: 'Blötsnö',
        winter_rain_snow: 'Regn och snö',
        winter_ice_pellets: 'Iskorn',
        winter_graupel: 'Snöhagel',
        winter_hail: 'Hagel',
        winter_drizzle: 'Duggregn',
        winter_freezing_drizzle: 'Underkylt duggregn',
        winter_setup: 'Aktivera lokalt vinterväder i SMHI Alerts och välj sedan en vintervädersensor.',
        thunder_title: 'Åsksannolikhet',
        thunder_caption: 'Lokal SMHI-prognos för varje angiven tidpunkt.',
        thunder_next_time: 'Nästa prognostid',
        thunder_forecast: 'Prognostider · Nästa 48 timmar',
        thunder_time: 'Prognostid',
        thunder_probability: 'Sannolikhet',
        thunder_created: 'Skapad',
        thunder_unknown: 'Data saknas',
        thunder_unavailable: 'Åsksannolikhet är inte tillgänglig',
        fire_title: 'Lokal brandrisk',
        fire_caption: 'Prognos för vald punkt · Idag. Eldningsförbud beslutas separat.',
        fire_forest_fire_risk: 'Skog',
        fire_grass_fire_risk: 'Gräs',
        fire_forest_dryness: 'Bränsleuttorkning',
        fire_forecast: 'Kommande dagar',
        fire_day: 'Dag',
        fire_updated: 'Uppdaterad',
        fire_unavailable: 'Dagens brandrisk är inte tillgänglig',
        fire_unknown: 'Data saknas',
        fire_forest_fire_risk_very_low: 'Mycket liten',
        fire_forest_fire_risk_low: 'Liten',
        fire_forest_fire_risk_moderate: 'Måttlig',
        fire_forest_fire_risk_high: 'Stor',
        fire_forest_fire_risk_very_high: 'Mycket stor',
        fire_forest_fire_risk_extreme: 'Extremt stor',
        fire_grass_fire_risk_snow_covered: 'Snötäckt mark',
        fire_grass_fire_risk_season_over: 'Säsongen är slut',
        fire_grass_fire_risk_low: 'Liten',
        fire_grass_fire_risk_moderate: 'Måttlig',
        fire_grass_fire_risk_high: 'Stor',
        fire_grass_fire_risk_very_high: 'Mycket stor',
        fire_forest_dryness_very_wet: 'Mycket blött',
        fire_forest_dryness_wet: 'Blött',
        fire_forest_dryness_moderately_wet: 'Måttligt blött',
        fire_forest_dryness_dry: 'Torrt',
        fire_forest_dryness_very_dry: 'Mycket torrt',
        fire_forest_dryness_extremely_dry: 'Extremt torrt',

    entity: 'Sensor', title: 'Rubrik', show_forecast: 'Visa prognos',
    forecast_expanded: 'Visa prognosen utfälld från början',
    fire_setup: 'Aktivera lokal brandrisk i SMHI Alerts och välj sedan en brandrisksensor.',
    thunder_setup: 'Aktivera lokal åsksannolikhet i SMHI Alerts och välj sedan dess sensor.',
  },
};
const forecastText = (hass, key) => {
  const language = (hass?.language || 'en').toLowerCase().split('-')[0];
  return (FORECAST_TEXT[language] || FORECAST_TEXT.en)[key] || key;
};
const snowDepthEntities = (hass) => Object.entries(hass?.states || {})
  .filter(([id, state]) => id.startsWith('sensor.') && state.attributes?.source_kind === 'snow_depth_observation')
  .map(([id]) => id);
const FORECAST_SOURCE_KINDS = {
  fire: 'local_fire_risk_forecast', thunder: THUNDER_SOURCE_KIND, winter: 'local_winter_forecast',
  wind: 'local_wind_forecast', precipitation: 'local_precipitation_forecast', analysis: 'local_weather_analysis',
};
const forecastEntities = (hass, kind) => Object.entries(hass?.states || {})
  .filter(([id, state]) => id.startsWith('sensor.') && (state.attributes?.source_kind === FORECAST_SOURCE_KINDS[kind]
    || (kind === 'fire' && state.state === 'unavailable' && state.attributes?.device_class === 'enum'
      && Object.values(FIRE_RISK_VALUES).some((options) => JSON.stringify(options) === JSON.stringify(state.attributes.options)))))
  .map(([id]) => id);

class SmhiForecastCard extends LitElement {
  static properties = { hass: {}, config: {} };
  static styles = css`
    :host { display: block; }
    ha-card { padding: 20px; color: var(--primary-text-color); }
    .setup { margin: 0; line-height: 1.5; color: var(--secondary-text-color); }
    .fire-risk-heading { display: flex; align-items: center; gap: 8px; }
    .fire-risk-heading ha-icon { --mdc-icon-size: 22px; color: var(--secondary-text-color); }
    .fire-risk h3 { margin: 0; font-size: 1.15em; font-weight: 500; }
    .fire-risk-caption, .fire-risk-updated { color: var(--secondary-text-color); font-size: 0.8em; line-height: 1.5; }
    .fire-risk-caption { margin: 5px 0 12px; }
    .fire-risk-current { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0; }
    .fire-risk-current dt { color: var(--secondary-text-color); font-size: 0.8em; line-height: 1.4; }
    .fire-risk-current dd { margin: 4px 0 0; font-weight: 600; line-height: 1.4; overflow-wrap: anywhere; }
    .fire-risk-unknown { color: var(--secondary-text-color); }
    .fire-risk-unavailable { margin: 0; color: var(--secondary-text-color); }
    .fire-risk-forecast { margin-top: 14px; border-top: 1px solid var(--divider-color); }
    .fire-risk-forecast summary { padding: 12px 0 4px; cursor: pointer; font-size: 0.9em; }
    .fire-risk-forecast summary:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 3px; }
    .fire-risk-forecast table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 6px; font-size: 0.8em; }
    .fire-risk-forecast th, .fire-risk-forecast td { padding: 9px 4px; text-align: start; vertical-align: top; line-height: 1.4; overflow-wrap: anywhere; }
    .fire-risk-forecast thead th { color: var(--secondary-text-color); font-weight: 400; }
    .fire-risk-forecast tbody th { font-weight: 500; }
    .fire-risk-forecast tbody tr + tr { border-top: 1px solid var(--divider-color); }
    .fire-risk-forecast th:first-child { width: 20%; padding-inline-start: 0; }
    .fire-risk-updated { margin-top: 12px; }
    .thunder-heading { display: flex; align-items: center; gap: 8px; }
    .thunder-heading ha-icon { --mdc-icon-size: 22px; color: var(--secondary-text-color); }
    .thunder-heading h3 { margin: 0; font-size: 1.15em; font-weight: 500; }
    .thunder-caption, .thunder-updated { color: var(--secondary-text-color); font-size: 0.8em; line-height: 1.5; }
    .thunder-caption { margin: 5px 0 12px; }
    .thunder-current { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .thunder-value { font-size: 1.75em; font-weight: 600; line-height: 1.2; font-variant-numeric: tabular-nums; }
    .thunder-time { display: flex; flex-direction: column; gap: 2px; font-size: 0.85em; }
    .thunder-time-label, .thunder-unknown, .thunder-unavailable { color: var(--secondary-text-color); }
    .thunder-forecast { margin-top: 14px; border-top: 1px solid var(--divider-color); }
    .thunder-forecast summary { padding: 12px 0 4px; cursor: pointer; font-size: 0.9em; }
    .thunder-forecast summary:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 3px; }
    .thunder-forecast table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 6px; font-size: 0.85em; }
    .thunder-forecast th, .thunder-forecast td { padding: 9px 4px; text-align: start; vertical-align: top; line-height: 1.4; overflow-wrap: anywhere; }
    .thunder-forecast th:first-child { width: 64%; padding-inline-start: 0; }
    .thunder-forecast thead th { color: var(--secondary-text-color); font-weight: 400; }
    .thunder-forecast tbody th { font-weight: 500; }
    .thunder-forecast tbody tr + tr { border-top: 1px solid var(--divider-color); }
    .thunder-forecast td { font-variant-numeric: tabular-nums; }
    .thunder-updated { margin-top: 12px; }

    .thunder-forecast .forecast-scroll { max-height: 360px; overflow: auto; }
    .thunder-forecast thead { position: sticky; top: 0; background: var(--ha-card-background, var(--card-background-color)); }
    .thunder-value { font-size: 2.5em; font-weight: 500; }
    .winter-heading { display: flex; align-items: center; gap: 8px; }
    .winter-heading ha-icon { --mdc-icon-size: 22px; color: var(--secondary-text-color); }
    .winter-heading h3 { margin: 0; font-size: 1.15em; font-weight: 500; }
    .winter-caption, .winter-updated { color: var(--secondary-text-color); font-size: 0.8em; line-height: 1.5; }
    .winter-caption { margin: 5px 0 14px; }
    .winter-time { display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: 0.85em; }
    .winter-time-label, .winter-unknown, .winter-unavailable { color: var(--secondary-text-color); }
    .winter-condition { margin: 8px 0 16px; font-size: 1.7em; line-height: 1.2; font-weight: 500; overflow-wrap: anywhere; }
    .winter-metrics { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 16px; margin: 0; }
    .winter-metrics dt { font-size: 0.8em; line-height: 1.4; color: var(--secondary-text-color); }
    .winter-metrics dd { margin: 4px 0 0; font-size: 1.45em; line-height: 1.25; font-variant-numeric: tabular-nums; }
    .winter-forecast { margin-top: 16px; border-top: 1px solid var(--divider-color); }
    .winter-forecast summary { padding: 12px 0 4px; cursor: pointer; font-size: 0.9em; }
    .winter-forecast summary:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 3px; }
    .winter-forecast .forecast-scroll { max-height: 360px; overflow: auto; }
    .winter-forecast table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 6px; font-size: 0.85em; }
    .winter-forecast th, .winter-forecast td { padding: 10px 4px; text-align: start; vertical-align: top; line-height: 1.4; overflow-wrap: anywhere; }
    .winter-forecast th:first-child { width: 48%; padding-inline-start: 0; }
    .winter-forecast thead { position: sticky; top: 0; background: var(--ha-card-background, var(--card-background-color)); }
    .winter-forecast thead th { color: var(--secondary-text-color); font-weight: 400; }
    .winter-forecast tbody th { font-weight: 500; }
    .winter-forecast tbody th time { display: block; font-size: 0.9em; font-weight: 400; color: var(--secondary-text-color); }
    .winter-forecast tbody tr + tr { border-top: 1px solid var(--divider-color); }
    .winter-forecast td { font-variant-numeric: tabular-nums; }
    .winter-updated { margin-top: 12px; }
    .snow-depth { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--divider-color); }
    .snow-depth-heading { display: flex; align-items: center; gap: 8px; }
    .snow-depth-heading ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
    .snow-depth-heading h4 { margin: 0; font-size: 1em; font-weight: 500; }
    .snow-depth-value { margin: 10px 0 8px; font-size: 1.7em; line-height: 1.25; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .snow-depth-unknown { color: var(--secondary-text-color); font-size: 1em; }
    .snow-depth-station { margin: 0 0 8px; font-size: 0.85em; line-height: 1.5; overflow-wrap: anywhere; }
    .snow-depth-meta { margin: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 10px; font-size: 0.8em; line-height: 1.5; }
    .snow-depth-meta dt { color: var(--secondary-text-color); }
    .snow-depth-meta dd { margin: 0; overflow-wrap: anywhere; }

    .weather-heading { display: flex; align-items: center; gap: 8px; }
    .weather-heading ha-icon { --mdc-icon-size: 22px; color: var(--secondary-text-color); }
    .weather-heading h3 { margin: 0; font-size: 1.15em; font-weight: 500; }
    .weather-caption, .weather-updated { color: var(--secondary-text-color); font-size: 0.8em; line-height: 1.5; }
    .weather-caption { margin: 5px 0 14px; }
    .weather-time { display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: 0.85em; line-height: 1.5; }
    .weather-time > span:first-child { color: var(--secondary-text-color); }
    .weather-value { margin: 8px 0 16px; font-size: 2.5em; line-height: 1.2; font-weight: 500; font-variant-numeric: tabular-nums; }
    .weather-unknown, .weather-unavailable { color: var(--secondary-text-color); }
    .weather-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 16px 0 0; }
    .weather-metrics dt { font-size: 0.8em; line-height: 1.4; color: var(--secondary-text-color); }
    .weather-metrics dd { margin: 4px 0 0; font-size: 1.5em; line-height: 1.3; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .weather-maximum { display: flex; flex-direction: column; gap: 4px; line-height: 1.4; }
    .weather-maximum > span, .weather-maximum small { color: var(--secondary-text-color); font-size: 0.8em; }
    .weather-maximum strong { font-size: 1.5em; font-weight: 500; font-variant-numeric: tabular-nums; }
    .weather-maximum time { font-size: 0.85em; }
    .weather-series { margin-top: 16px; border-top: 1px solid var(--divider-color); }
    .weather-series summary { padding: 12px 0 4px; cursor: pointer; font-size: 0.9em; }
    .weather-series summary:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 3px; }
    .weather-series .forecast-scroll { max-height: 360px; overflow: auto; }
    .weather-series table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 6px; font-size: 0.85em; }
    .weather-series th, .weather-series td { padding: 10px 4px; text-align: start; vertical-align: top; line-height: 1.4; overflow-wrap: anywhere; }
    .weather-series th:first-child { width: 44%; padding-inline-start: 0; }
    .weather-series thead { position: sticky; top: 0; background: var(--ha-card-background, var(--card-background-color)); }
    .weather-series thead th { color: var(--secondary-text-color); font-weight: 400; }
    .weather-series tbody th { font-weight: 500; }
    .weather-series tbody tr + tr { border-top: 1px solid var(--divider-color); }
    .weather-series td { font-variant-numeric: tabular-nums; }
    .weather-updated { margin-top: 12px; }
    @media (max-width: 400px) {
      ha-card { padding: 16px; }
      .fire-risk-current { gap: 8px; }
      .fire-risk-current dd { font-size: 0.95em; }
    }
  `;

  setConfig(config) {
    const entity = typeof config.entity === 'string' ? config.entity.trim() : '';
    if (entity && !/^sensor\.[a-z0-9_]+$/.test(entity)) throw new Error('Select a sensor entity.');
    this.config = { ...config, entity, show_forecast: config.show_forecast !== false,
      forecast_expanded: config.forecast_expanded === true };
    this._forecastOpen = this.config.forecast_expanded;
  }

  connectedCallback() {
    super.connectedCallback();
    // Expire displayed forecast times even when no HA entity has changed.
    this._clockTimer = setInterval(() => this.requestUpdate(), 60000);
  }

  disconnectedCallback() {
    clearInterval(this._clockTimer);
    super.disconnectedCallback();
  }

  _forecastToggled = (event) => { this._forecastOpen = event.target.open; };

  getCardSize() { return 5; }
  getGridOptions() { return { columns: 12, min_columns: 6, max_columns: 12, min_rows: 3 }; }

  shouldUpdate(changed) {
    if (changed.has('config')) return true;
    if (changed.has('hass')) {
      const state = this.hass?.states?.[this.config?.entity];
      const snow = this.constructor.kind === 'winter' ? this.hass?.states?.[this.config?.snow_depth_entity] : null;
      const time = this.constructor.kind === 'fire' ? this._fireRiskToday()
        : Math.floor((this.constructor.kind === 'winter' ? this._winterNow() : this._weatherNow?.() ?? this._thunderNow()) / 60000);
      const key = JSON.stringify([state?.state, state?.attributes, snow?.state, snow?.attributes, this.hass?.language,
        this.hass?.locale?.language, this.hass?.locale?.time_format, this.hass?.locale?.time_zone,
        this.hass?.config?.time_zone, this.hass?.config?.unit_system, time]);
      if (this._lastKey === key) return false;
      this._lastKey = key;
    }
    return true;
  }

  _t(key) { return forecastText(this.hass, key); }
  _parseDate(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  _formatDate(value) {
    const date = this._parseDate(value);
    if (!date) return '';
    const locale = this.hass?.locale;
    const language = locale?.language || this.hass?.language || 'en';
    const timeFormat = locale?.time_format;
    // HA profile values are '12', '24', 'language' or 'system' (browser default).
    const useAmPm = timeFormat === '12' || (timeFormat !== '24'
      && new Intl.DateTimeFormat(timeFormat === 'system' ? undefined : language, {
        hour: 'numeric',
      }).resolvedOptions().hour12);
    return new Intl.DateTimeFormat(language, {
      day: 'numeric', month: 'short', hour: useAmPm ? 'numeric' : '2-digit', minute: '2-digit',
      // h23 keeps midnight at 00:00 even when the display language is English.
      hourCycle: useAmPm ? 'h12' : 'h23',
      timeZone: locale?.time_zone === 'local' ? undefined : this.hass?.config?.time_zone,
    }).format(date);
  }

  render() {
    if (!this.hass || !this.config) return html``;
    return html`<ha-card>${!this.config.entity
      ? html`<p class="setup">${this._t(`${this.constructor.kind}_setup`)}</p>`
      : this.constructor.kind === 'fire' ? this._renderFireRisk()
        : this.constructor.kind === 'winter' ? this._renderWinterWeather() : this._renderThunderProbability()}</ha-card>`;
  }

  static getConfigElement() { return document.createElement(`smhi-${this.kind === 'fire' ? 'fire-risk' : this.kind}-card-editor`); }
  static getStubConfig(hass) { return { entity: forecastEntities(hass, this.kind)[0] || '' }; }
}

class SmhiFireRiskCard extends SmhiForecastCard {
  static kind = 'fire';
  _fireRiskToday() {
    return new Intl.DateTimeFormat('sv-SE', {
      timeZone: 'Europe/Stockholm', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date());
  }

  _fireRiskDay(row) {
    if (!row || typeof row !== 'object' || !/^\d{4}-\d{2}-\d{2}$/.test(row.date)) return null;
    const date = new Date(`${row.date}T12:00:00Z`);
    if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== row.date) return null;
    const result = { date: row.date };
    for (const [key, values] of Object.entries(FIRE_RISK_VALUES)) {
      result[key] = values.includes(row[key]) ? row[key] : null;
    }
    return result;
  }

  _fireRiskData() {
    const state = this.hass?.states?.[this.config?.entity];
    const attrs = state?.attributes;
    if (!state || (state.state !== 'unknown' && !Object.values(FIRE_RISK_VALUES).some((values) => values.includes(state.state)))
      || attrs?.source_kind !== 'local_fire_risk_forecast') return null;
    const today = this._fireRiskToday();
    const current = this._fireRiskDay(attrs.current);
    const seen = new Set();
    const forecast = (Array.isArray(attrs.forecast) ? attrs.forecast : [])
      .map((row) => this._fireRiskDay(row))
      .filter((row) => row && row.date > today)
      .sort((a, b) => a.date.localeCompare(b.date))
      .filter((row) => !seen.has(row.date) && seen.add(row.date))
      .slice(0, 6);
    return { current: current?.date === today ? current : null, forecast, approved: attrs.approved_time };
  }

  _fireRiskLabel(key, value) {
    if (!FIRE_RISK_VALUES[key]?.includes(value)) return this._t('fire_unknown');
    const label = this._t(`fire_${key}_${value}`);
    return value === 'extreme' || value === 'extremely_dry' ? `5E · ${label}` : label;
  }

  _fireRiskDate(value) {
    return new Intl.DateTimeFormat(this.hass?.language || 'en', {
      weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC',
    }).format(new Date(`${value}T12:00:00Z`));
  }

  _renderFireRisk() {
    const data = this._fireRiskData();
    const keys = Object.keys(FIRE_RISK_VALUES);
    const approved = data?.approved && this._parseDate(data.approved);
    return html`
      <section class="fire-risk" aria-label=${this.config.title || this._t('fire_title')}>
        <div class="fire-risk-heading">
          <ha-icon icon="mdi:pine-tree" aria-hidden="true"></ha-icon>
          <h3>${this.config.title || this._t('fire_title')}</h3>
        </div>
        <p class="fire-risk-caption">${this._t('fire_caption')}</p>
        ${data?.current ? html`
          <dl class="fire-risk-current">
            ${keys.map((key) => html`<div>
              <dt>${this._t(`fire_${key}`)}</dt>
              <dd class=${data.current[key] ? '' : 'fire-risk-unknown'}>${this._fireRiskLabel(key, data.current[key])}</dd>
            </div>`)}
          </dl>` : html`<p class="fire-risk-unavailable">${this._t('fire_unavailable')}</p>`}
        ${this.config.show_forecast && data?.forecast.length ? html`
          <details class="fire-risk-forecast" .open=${this._forecastOpen} @toggle=${this._forecastToggled}>
            <summary>${this._t('fire_forecast')} (${data.forecast.length})</summary>
            <table>
              <thead><tr><th scope="col">${this._t('fire_day')}</th>${keys.map((key) => html`<th scope="col">${this._t(`fire_${key}`)}</th>`)}</tr></thead>
              <tbody>${data.forecast.map((row) => html`
                <tr><th scope="row">${this._fireRiskDate(row.date)}</th>${keys.map((key) => html`
                  <td class=${row[key] ? '' : 'fire-risk-unknown'}>${this._fireRiskLabel(key, row[key])}</td>`)}</tr>
              `)}</tbody>
            </table>
          </details>` : html``}
        ${approved ? html`<div class="fire-risk-updated">SMHI · ${this._t('fire_updated')} ${this._formatDate(approved)}</div>` : html``}
      </section>
    `;
  }


}

class SmhiThunderCard extends SmhiForecastCard {
  static kind = 'thunder';
  _thunderNow() {
    return Date.now();
  }

  _thunderPercent(value) {
    if ((typeof value !== 'number' && typeof value !== 'string')
      || (typeof value === 'string' && !value.trim())) return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 && number <= 100 ? number : null;
  }

  _thunderPoint(row, now) {
    if (!row || typeof row !== 'object' || typeof row.valid_time !== 'string') return null;
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(row.valid_time)) return null;
    const date = this._parseDate(row.valid_time);
    if (!date || date.getTime() <= now || date.getTime() > now + 48 * 60 * 60 * 1000) return null;
    return { valid_time: date.toISOString(), probability: this._thunderPercent(row.probability) };
  }

  _thunderData() {
    const state = this.hass?.states?.[this.config?.entity];
    const attrs = state?.attributes;
    if (!state || attrs?.source_kind !== THUNDER_SOURCE_KIND
      || attrs.probability_unit !== '%'
      || (state.state !== 'unknown' && this._thunderPercent(state.state) === null)) return null;
    const now = this._thunderNow();
    const current = this._thunderPoint(attrs.current, now);
    // Unknown at the nearest forecast time must not be replaced with a later value.
    if (current && state.state === 'unknown') current.probability = null;
    const seen = new Set();
    const forecast = (Array.isArray(attrs.forecast) ? attrs.forecast : [])
      .map((row) => this._thunderPoint(row, now))
      .filter((row) => row)
      .sort((a, b) => a.valid_time.localeCompare(b.valid_time))
      .filter((row) => !seen.has(row.valid_time) && seen.add(row.valid_time));
    return { current, forecast, created: attrs.created_time };
  }

  _thunderLabel(value) {
    if (value === null) return this._t('thunder_unknown');
    // Preserve the source's percentage, including a real zero, without risk bands.
    return `${new Intl.NumberFormat(this.hass?.language || 'en', { maximumFractionDigits: 10 }).format(value)} %`;
  }

  _renderThunderProbability() {
    const data = this._thunderData();
    const created = data?.created && this._parseDate(data.created);
    return html`
      <section class="thunder-probability" aria-label=${this.config.title || this._t('thunder_title')}>
        <div class="thunder-heading">
          <ha-icon icon="mdi:weather-lightning" aria-hidden="true"></ha-icon>
          <h3>${this.config.title || this._t('thunder_title')}</h3>
        </div>
        <p class="thunder-caption">${this._t('thunder_caption')}</p>
        ${data?.current ? html`
          <div class="thunder-current">
            <div class=${data.current.probability === null ? 'thunder-value thunder-unknown' : 'thunder-value'}>${this._thunderLabel(data.current.probability)}</div>
            <div class="thunder-time">
              <span class="thunder-time-label">${this._t('thunder_next_time')}</span>
              <time datetime=${data.current.valid_time}>${this._formatDate(data.current.valid_time)}</time>
            </div>
          </div>` : html`<p class="thunder-unavailable">${this._t('thunder_unavailable')}</p>`}
        ${this.config.show_forecast && data?.forecast.length ? html`
          <details class="thunder-forecast" .open=${this._forecastOpen} @toggle=${this._forecastToggled}>
            <summary>${this._t('thunder_forecast')}</summary>
            <div class="forecast-scroll"><table>
              <thead><tr><th scope="col">${this._t('thunder_time')}</th><th scope="col">${this._t('thunder_probability')}</th></tr></thead>
              <tbody>${data.forecast.map((row) => html`
                <tr><th scope="row"><time datetime=${row.valid_time}>${this._formatDate(row.valid_time)}</time></th>
                  <td class=${row.probability === null ? 'thunder-unknown' : ''}>${this._thunderLabel(row.probability)}</td></tr>
              `)}</tbody>
            </table></div>
          </details>` : html``}
        ${created ? html`<div class="thunder-updated">SMHI · ${this._t('thunder_created')} ${this._formatDate(created)}</div>` : html``}
      </section>
    `;
  }


}


const WINTER_PRECIPITATION_TYPES = [
  'none', 'rain', 'thunderstorm', 'freezing_rain', 'mixed_ice', 'snow', 'wet_snow',
  'rain_snow', 'ice_pellets', 'graupel', 'hail', 'drizzle', 'freezing_drizzle',
];

class SmhiWinterCard extends SmhiForecastCard {
  static kind = 'winter';

  setConfig(config) {
    const snowEntity = typeof config.snow_depth_entity === 'string' ? config.snow_depth_entity.trim() : '';
    if (snowEntity && !/^sensor\.[a-z0-9_]+$/.test(snowEntity)) throw new Error('Select a snow depth sensor entity.');
    const next = { ...config };
    if (snowEntity) next.snow_depth_entity = snowEntity;
    else delete next.snow_depth_entity;
    super.setConfig(next);
  }

  render() {
    if (!this.hass || !this.config) return html``;
    return html`<ha-card>${this.config.entity ? this._renderWinterWeather()
      : html`<p class="setup">${this._t('winter_setup')}</p>`}${this._renderSnowDepth()}</ha-card>`;
  }

  _winterNow() { return Date.now(); }

  _winterNumber(value, min, max) {
    // Forecast attributes contain numbers, never HA's formatted state strings.
    return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max ? value : null;
  }

  _winterPoint(row, now) {
    if (!row || typeof row !== 'object' || typeof row.valid_time !== 'string') return null;
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(row.valid_time)) return null;
    const date = this._parseDate(row.valid_time);
    if (!date || date.getTime() <= now || date.getTime() > now + 48 * 60 * 60 * 1000) return null;
    return {
      valid_time: date.toISOString(),
      precipitation_type: WINTER_PRECIPITATION_TYPES.includes(row.precipitation_type) ? row.precipitation_type : null,
      frozen_probability: this._winterNumber(row.frozen_probability, 0, 100),
      temperature: this._winterNumber(row.temperature, -100, 100),
    };
  }

  _winterData() {
    const state = this.hass?.states?.[this.config?.entity];
    const attrs = state?.attributes;
    if (!state || attrs?.source_kind !== 'local_winter_forecast'
      || state.state === 'unavailable' || !state.state) return null;
    const now = this._winterNow();
    const current = this._winterPoint(attrs.current, now);
    const seen = new Set();
    const forecast = (Array.isArray(attrs.forecast) ? attrs.forecast : [])
      .map((row) => this._winterPoint(row, now))
      .filter((row) => row)
      .sort((a, b) => a.valid_time.localeCompare(b.valid_time))
      .filter((row) => !seen.has(row.valid_time) && seen.add(row.valid_time));
    // The selected sensor can be unknown while its sibling values are valid.
    return { current, forecast, created: attrs.created_time };
  }

  _winterTypeLabel(value) {
    return WINTER_PRECIPITATION_TYPES.includes(value) ? this._t(`winter_${value}`) : this._t('winter_unknown');
  }

  _winterValue(value, unit) {
    if (value === null) return this._t('winter_unknown');
    const number = new Intl.NumberFormat(this.hass?.locale?.language || this.hass?.language || 'en', {
      maximumFractionDigits: 1,
    }).format(value);
    return `${number} ${unit}`;
  }

  _winterTemperature(value) {
    const unit = this.hass?.config?.unit_system?.temperature === '°F' ? '°F' : '°C';
    return this._winterValue(value === null ? null : unit === '°F' ? value * 9 / 5 + 32 : value, unit);
  }

  _snowDepthData() {
    if (!this.config?.snow_depth_entity) return null;
    const state = this.hass?.states?.[this.config.snow_depth_entity];
    const attrs = state?.attributes;
    if (attrs?.source_kind !== 'snow_depth_observation') return { status: 'unavailable' };
    const parseTime = (value) => typeof value === 'string'
      && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      ? this._parseDate(value) : null;
    const observed = parseTime(attrs.observation_time);
    const expires = parseTime(attrs.expires_at);
    const stale = attrs.stale === true || (expires && this._winterNow() >= expires.getTime());
    const available = state.state !== 'unavailable' && Boolean(state.state);
    const fresh = available && !stale && observed && expires;
    const depth = fresh && state.state !== 'unknown' && attrs.quality === 'G'
      ? this._winterNumber(attrs.depth_cm, 0, 300) : null;
    const cover = fresh && ['trace', 'patchy'].includes(attrs.snow_cover) ? attrs.snow_cover : null;
    return {
      status: stale ? 'stale' : !available ? 'unavailable' : depth !== null || cover ? 'fresh' : 'unknown',
      depth, cover,
      station: typeof attrs.station_name === 'string' ? attrs.station_name
        : typeof attrs.station_id === 'string' ? attrs.station_id : null,
      distance: this._winterNumber(attrs.distance_km, 0, Number.MAX_VALUE),
      observed: observed?.toISOString(),
      quality: attrs.quality === 'G' ? 'g' : attrs.quality === 'Y' ? 'y' : 'unknown',
    };
  }

  _renderSnowDepth() {
    const data = this._snowDepthData();
    if (!data) return html``;
    const value = data.status === 'fresh' ? data.cover ? this._t(`snow_depth_${data.cover}`)
      : this._winterValue(data.depth, 'cm') : this._t(`snow_depth_${data.status}`);
    return html`
      <section class="snow-depth" aria-label=${this._t('snow_depth_title')}>
        <div class="snow-depth-heading"><ha-icon icon="mdi:snowflake" aria-hidden="true"></ha-icon>
          <h4>${this._t('snow_depth_title')}</h4></div>
        <p class=${data.status === 'fresh' && data.depth !== null ? 'snow-depth-value' : 'snow-depth-value snow-depth-unknown'}>${value}</p>
        <p class="snow-depth-station">${this._t('snow_depth_station')}: ${data.station || this._t('snow_depth_station_unknown')}${data.distance !== null && data.distance !== undefined ? html` · ${this._winterValue(data.distance, 'km')}` : html``}</p>
        <dl class="snow-depth-meta">
          ${data.observed ? html`<dt>${this._t('snow_depth_observed')}</dt><dd><time datetime=${data.observed}>${this._formatDate(data.observed)}</time></dd>` : html``}
          <dt>${this._t('snow_depth_quality')}</dt><dd>${this._t(`snow_depth_quality_${data.quality || 'unknown'}`)}</dd>
        </dl>
      </section>
    `;
  }

  _renderWinterWeather() {
    const data = this._winterData();
    const created = data?.created && this._parseDate(data.created);
    return html`
      <section class="winter-weather" aria-label=${this.config.title || this._t('winter_title')}>
        <div class="winter-heading">
          <ha-icon icon="mdi:weather-snowy-rainy" aria-hidden="true"></ha-icon>
          <h3>${this.config.title || this._t('winter_title')}</h3>
        </div>
        <p class="winter-caption">${this._t('winter_caption')}</p>
        ${data?.current ? html`
          <div class="winter-time">
            <span class="winter-time-label">${this._t('winter_next_time')}</span>
            <time datetime=${data.current.valid_time}>${this._formatDate(data.current.valid_time)}</time>
          </div>
          <p class=${data.current.precipitation_type === null ? 'winter-condition winter-unknown' : 'winter-condition'}>${this._winterTypeLabel(data.current.precipitation_type)}</p>
          <dl class="winter-metrics">
            <div><dt>${this._t('winter_probability')}</dt>
              <dd class=${data.current.frozen_probability === null ? 'winter-unknown' : ''}>${this._winterValue(data.current.frozen_probability, '%')}</dd></div>
            <div><dt>${this._t('winter_temperature')}</dt>
              <dd class=${data.current.temperature === null ? 'winter-unknown' : ''}>${this._winterTemperature(data.current.temperature)}</dd></div>
          </dl>` : html`<p class="winter-unavailable">${this._t('winter_unavailable')}</p>`}
        ${this.config.show_forecast && data?.forecast.length ? html`
          <details class="winter-forecast" .open=${this._forecastOpen} @toggle=${this._forecastToggled}>
            <summary>${this._t('winter_forecast')}</summary>
            <div class="forecast-scroll"><table>
              <thead><tr><th scope="col">${this._t('winter_time')}</th>
                <th scope="col" aria-label=${this._t('winter_probability')}>${this._t('winter_probability_short')}</th>
                <th scope="col" aria-label=${this._t('winter_temperature')}>${this._t('winter_temperature_short')}</th></tr></thead>
              <tbody>${data.forecast.map((row) => html`
                <tr><th scope="row"><time datetime=${row.valid_time}>${this._formatDate(row.valid_time)}</time>${this._winterTypeLabel(row.precipitation_type)}</th>
                  <td class=${row.frozen_probability === null ? 'winter-unknown' : ''}>${this._winterValue(row.frozen_probability, '%')}</td>
                  <td class=${row.temperature === null ? 'winter-unknown' : ''}>${this._winterTemperature(row.temperature)}</td></tr>
              `)}</tbody>
            </table></div>
          </details>` : html``}
        ${created ? html`<div class="winter-updated">SMHI · ${this._t('winter_created')} ${this._formatDate(created)}</div>` : html``}
      </section>
    `;
  }
}

// Point forecasts and past MESAN analyses keep their time semantics separate.
class SmhiWeatherSourceCard extends SmhiForecastCard {
  _weatherNow() { return Date.now(); }

  _sourceNumber(value, min = 0, max = Number.MAX_VALUE) {
    return typeof value === 'number' && Number.isFinite(value) && value !== 9999
      && value >= min && value <= max ? value : null;
  }

  _sourceTime(value) {
    return typeof value === 'string'
      && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      ? this._parseDate(value) : null;
  }

  _sourcePoint(row, now) {
    if (!row || typeof row !== 'object') return null;
    const valid = this._sourceTime(row.valid_time);
    const analysis = this.constructor.kind === 'analysis';
    if (!valid || (analysis
      ? valid.getTime() > now || valid.getTime() < now - 24 * 60 * 60 * 1000
      : valid.getTime() <= now || valid.getTime() > now + 48 * 60 * 60 * 1000)) return null;
    const point = { valid_time: valid.toISOString() };
    if (analysis) return { ...point,
      precipitation: this._sourceNumber(row.precipitation),
      snow_change: this._sourceNumber(row.snow_change, -Number.MAX_VALUE),
    };
    if (this.constructor.kind === 'wind') return { ...point, gust: this._sourceNumber(row.gust) };
    const start = this._sourceTime(row.interval_start);
    const interval = start && start.getTime() < valid.getTime();
    return { ...point, interval_start: interval ? start.toISOString() : null,
      probability: interval ? this._sourceNumber(row.probability, 0, 100) : null,
      amount: interval ? this._sourceNumber(row.amount) : null,
    };
  }

  _sourceData() {
    const state = this.hass?.states?.[this.config?.entity];
    const attrs = state?.attributes;
    const kind = this.constructor.kind;
    if (!state || state.state === 'unavailable' || !state.state
      || attrs?.source_kind !== FORECAST_SOURCE_KINDS[kind]) return null;
    if ((kind === 'wind' && attrs.wind_unit !== 'm/s')
      || (kind === 'precipitation' && (attrs.amount_unit !== 'mm' || attrs.probability_unit !== '%'))
      || (kind === 'analysis' && (attrs.precipitation_unit !== 'mm' || attrs.snow_change_unit !== 'cm'))) return null;
    const now = this._weatherNow();
    const created = this._sourceTime(attrs.created_time);
    const maxAge = (kind === 'analysis' ? 3 : 2) * 60 * 60 * 1000;
    if (!created || now - created.getTime() >= maxAge || created.getTime() - now > 15 * 60 * 1000) return null;
    const current = this._sourcePoint(attrs.current, now);
    const rows = kind === 'analysis' ? attrs.history : attrs.forecast;
    const seen = new Set();
    const series = (Array.isArray(rows) ? rows : []).map((row) => this._sourcePoint(row, now))
      .filter(Boolean).sort((a, b) => kind === 'analysis'
        ? b.valid_time.localeCompare(a.valid_time) : a.valid_time.localeCompare(b.valid_time))
      .filter((row) => !seen.has(row.valid_time) && seen.add(row.valid_time));
    const maxTime = this._sourceTime(attrs.max_gust_time);
    const maxEnd = this._sourceTime(attrs.max_window_end);
    const maxValid = attrs.max_complete === true && maxTime && maxEnd
      && maxTime.getTime() > now && maxTime.getTime() <= Math.min(maxEnd.getTime(), now + 24 * 60 * 60 * 1000);
    return { current, series, created: created.toISOString(),
      maximum: maxValid ? this._sourceNumber(attrs.max_gust_24h) : null,
      maximum_time: maxValid ? maxTime.toISOString() : null,
      maximum_end: maxEnd?.toISOString(),
    };
  }

  _sourceValue(value, unit, maximumFractionDigits = 1) {
    if (value === null) return this._t('weather_unknown');
    return `${new Intl.NumberFormat(this.hass?.locale?.language || this.hass?.language || 'en', {
      maximumFractionDigits,
    }).format(value)} ${unit}`;
  }

  _windValue(value) {
    const preferred = this.hass?.config?.unit_system?.wind_speed;
    const conversions = { 'm/s': 1, 'km/h': 3.6, mph: 2.2369362920544, 'mi/h': 2.2369362920544, kn: 1.9438444924406, 'ft/s': 3.2808398950131 };
    const unit = Object.hasOwn(conversions, preferred) ? preferred : 'm/s';
    return this._sourceValue(value === null ? null : value * conversions[unit], unit);
  }

  _precipitationValue(value) {
    const inches = this.hass?.config?.unit_system?.accumulated_precipitation === 'in';
    return this._sourceValue(value === null ? null : inches ? value / 25.4 : value, inches ? 'in' : 'mm', inches ? 4 : 2);
  }

  _snowChangeValue(value) {
    const inches = this.hass?.config?.unit_system?.accumulated_precipitation === 'in';
    return this._sourceValue(value === null ? null : inches ? value / 2.54 : value, inches ? 'in' : 'cm', inches ? 4 : 2);
  }

  _sourceInterval(row, analysis = false) {
    const start = analysis ? new Date(Date.parse(row.valid_time) - 60 * 60 * 1000).toISOString() : row.interval_start;
    return start ? html`<time datetime=${start}>${this._formatDate(start)}</time> – <time datetime=${row.valid_time}>${this._formatDate(row.valid_time)}</time>`
      : html`${this._t('precipitation_interval_unknown')}`;
  }

  _sourceCurrent(data) {
    const row = data.current;
    const kind = this.constructor.kind;
    if (kind === 'wind') return html`
      <div class="weather-time"><span>${this._t('weather_next_time')}</span><time datetime=${row.valid_time}>${this._formatDate(row.valid_time)}</time></div>
      <p class=${row.gust === null ? 'weather-value weather-unknown' : 'weather-value'}>${this._windValue(row.gust)}</p>
      <div class="weather-maximum"><span>${this._t('wind_maximum')}</span>
        <strong class=${data.maximum === null ? 'weather-unknown' : ''}>${this._windValue(data.maximum)}</strong>
        ${data.maximum_time ? html`<time datetime=${data.maximum_time}>${this._formatDate(data.maximum_time)}</time>` : html``}
        ${data.maximum_end ? html`<small>${this._t('wind_window_end')} ${this._formatDate(data.maximum_end)}</small>` : html``}
      </div>`;
    const analysis = kind === 'analysis';
    const metrics = analysis ? [
      ['analysis_precipitation', this._precipitationValue(row.precipitation), row.precipitation],
      ['analysis_snow_change', this._snowChangeValue(row.snow_change), row.snow_change],
    ] : [
      ['precipitation_probability', this._sourceValue(row.probability, '%'), row.probability],
      ['precipitation_amount', this._precipitationValue(row.amount), row.amount],
    ];
    return html`
      <div class="weather-time"><span>${this._t(analysis ? 'analysis_period' : 'precipitation_period')}</span><span>${this._sourceInterval(row, analysis)}</span></div>
      <dl class="weather-metrics">${metrics.map(([label, text, value]) => html`<div><dt>${this._t(label)}</dt><dd class=${value === null ? 'weather-unknown' : ''}>${text}</dd></div>`)}</dl>`;
  }

  _sourceSeries(data) {
    const kind = this.constructor.kind;
    const analysis = kind === 'analysis';
    const headings = kind === 'wind' ? ['weather_time', 'wind_gust']
      : analysis ? ['analysis_period', 'analysis_precipitation_short', 'analysis_snow_change_short']
        : ['precipitation_period', 'precipitation_probability_short', 'precipitation_amount_short'];
    return html`
      <details class="weather-series" .open=${this._forecastOpen} @toggle=${this._forecastToggled}>
        <summary>${this._t(analysis ? 'analysis_history' : 'weather_forecast')}</summary>
        <div class="forecast-scroll"><table>
          <thead><tr>${headings.map((heading) => html`<th scope="col">${this._t(heading)}</th>`)}</tr></thead>
          <tbody>${data.series.map((row) => html`<tr>
            <th scope="row">${kind === 'wind' ? html`<time datetime=${row.valid_time}>${this._formatDate(row.valid_time)}</time>` : this._sourceInterval(row, analysis)}</th>
            ${kind === 'wind' ? html`<td class=${row.gust === null ? 'weather-unknown' : ''}>${this._windValue(row.gust)}</td>`
              : analysis ? html`<td class=${row.precipitation === null ? 'weather-unknown' : ''}>${this._precipitationValue(row.precipitation)}</td><td class=${row.snow_change === null ? 'weather-unknown' : ''}>${this._snowChangeValue(row.snow_change)}</td>`
                : html`<td class=${row.probability === null ? 'weather-unknown' : ''}>${this._sourceValue(row.probability, '%')}</td><td class=${row.amount === null ? 'weather-unknown' : ''}>${this._precipitationValue(row.amount)}</td>`}
          </tr>`)}</tbody>
        </table></div>
      </details>`;
  }

  render() {
    if (!this.hass || !this.config) return html``;
    const kind = this.constructor.kind;
    if (!this.config.entity) return html`<ha-card><p class="setup">${this._t(`${kind}_setup`)}</p></ha-card>`;
    const data = this._sourceData();
    const icons = { wind: 'mdi:weather-windy', precipitation: 'mdi:weather-rainy', analysis: 'mdi:chart-timeline-variant' };
    return html`<ha-card><section class="weather-source" aria-label=${this.config.title || this._t(`${kind}_title`)}>
      <div class="weather-heading"><ha-icon icon=${icons[kind]} aria-hidden="true"></ha-icon><h3>${this.config.title || this._t(`${kind}_title`)}</h3></div>
      <p class="weather-caption">${this._t(`${kind}_caption`)}</p>
      ${data?.current ? this._sourceCurrent(data) : html`<p class="weather-unavailable">${this._t(`${kind}_unavailable`)}</p>`}
      ${this.config.show_forecast && data?.series.length ? this._sourceSeries(data) : html``}
      ${data?.created ? html`<div class="weather-updated">SMHI · ${this._t('weather_created')} ${this._formatDate(data.created)}</div>` : html``}
    </section></ha-card>`;
  }
}

class SmhiWindCard extends SmhiWeatherSourceCard { static kind = 'wind'; }
class SmhiPrecipitationCard extends SmhiWeatherSourceCard { static kind = 'precipitation'; }
class SmhiAnalysisCard extends SmhiWeatherSourceCard { static kind = 'analysis'; }

class SmhiForecastCardEditor extends LitElement {
  static properties = { hass: {}, _config: {} };
  setConfig(config) { this._config = { ...config }; }
  render() {
    if (!this.hass || !this._config) return html``;
    const kind = this.constructor.kind;
    const entity = kind === 'fire'
      ? { filter: { domain: 'sensor', integration: 'smhi_alerts', device_class: 'enum' } }
      : { filter: { domain: 'sensor', integration: 'smhi_alerts' }, include_entities: forecastEntities(this.hass, kind) };
    const schema = [
      { name: 'entity', required: true, selector: { entity } },
      ...(kind === 'winter' ? [{ name: 'snow_depth_entity', selector: { entity: {
        filter: { domain: 'sensor', integration: 'smhi_alerts' }, include_entities: snowDepthEntities(this.hass),
      } } }] : []),
      { name: 'title', selector: { text: {} } },
      { name: 'show_forecast', selector: { boolean: {} } },
      ...(this._config.show_forecast !== false ? [{ name: 'forecast_expanded', selector: { boolean: {} } }] : []),
    ];
    const data = { title: '', ...this._config, show_forecast: this._config.show_forecast !== false,
      forecast_expanded: this._config.forecast_expanded === true };
    return html`<ha-form .hass=${this.hass} .data=${data} .schema=${schema}
      .computeLabel=${this._computeLabel} @value-changed=${this._valueChanged}></ha-form>`;
  }
  _computeLabel = (schema) => forecastText(this.hass, this.constructor.kind === 'analysis'
    ? ({ show_forecast: 'analysis_show_history', forecast_expanded: 'analysis_expand_history' }[schema.name] || schema.name) : schema.name);
  _valueChanged = (event) => {
    if (!this._config || !event.detail?.value) return;
    this._config = { ...this._config, ...event.detail.value };
    this.dispatchEvent(new CustomEvent('config-changed', {
      detail: { config: this._config }, bubbles: true, composed: true,
    }));
  };
}
class SmhiFireRiskCardEditor extends SmhiForecastCardEditor { static kind = 'fire'; }
class SmhiThunderCardEditor extends SmhiForecastCardEditor { static kind = 'thunder'; }
class SmhiWinterCardEditor extends SmhiForecastCardEditor { static kind = 'winter'; }
class SmhiWindCardEditor extends SmhiForecastCardEditor { static kind = 'wind'; }
class SmhiPrecipitationCardEditor extends SmhiForecastCardEditor { static kind = 'precipitation'; }
class SmhiAnalysisCardEditor extends SmhiForecastCardEditor { static kind = 'analysis'; }
for (const [name, element] of [
  ['smhi-fire-risk-card', SmhiFireRiskCard], ['smhi-fire-risk-card-editor', SmhiFireRiskCardEditor],
  ['smhi-thunder-card', SmhiThunderCard], ['smhi-thunder-card-editor', SmhiThunderCardEditor],
  ['smhi-winter-card', SmhiWinterCard], ['smhi-winter-card-editor', SmhiWinterCardEditor],
  ['smhi-wind-card', SmhiWindCard], ['smhi-wind-card-editor', SmhiWindCardEditor],
  ['smhi-precipitation-card', SmhiPrecipitationCard], ['smhi-precipitation-card-editor', SmhiPrecipitationCardEditor],
  ['smhi-analysis-card', SmhiAnalysisCard], ['smhi-analysis-card-editor', SmhiAnalysisCardEditor],
]) {
  if (!customElements.get(name)) customElements.define(name, element);
}

// Register the card so it appears in the "Add card" dialog
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'smhi-alert-card',
  name: 'SMHI Alert Card',
  description: 'Displays SMHI warnings for selected regions using the SMHI Weather Warnings & Alerts integration',
  preview: true,
});
window.customCards.push(
  { type: 'smhi-fire-risk-card', name: 'SMHI Fire Risk Card', preview: true,
    description: 'Local forest and grass fire risk, fuel drying and daily forecasts. Works independently of the alert card.' },
  { type: 'smhi-thunder-card', name: 'SMHI Thunder Card', preview: true,
    description: 'Local thunderstorm probability with exact forecast times for the next 48 hours. Works independently of the alert card.' },
  { type: 'smhi-winter-card', name: 'SMHI Winter Card', preview: true,
    description: 'Local precipitation type, frozen precipitation probability and temperature for the next 48 hours.' },
  { type: 'smhi-wind-card', name: 'SMHI Wind Card', preview: true,
    description: 'Local wind gust forecasts and the highest forecast value for the next 24 hours.' },
  { type: 'smhi-precipitation-card', name: 'SMHI Precipitation Card', preview: true,
    description: 'Local precipitation probability and water equivalent amounts for each exact forecast interval.' },
  { type: 'smhi-analysis-card', name: 'SMHI Analysis Card', preview: true,
    description: 'Past local MESAN precipitation and snow amount change with 24 hours of analysis history.' },
);


// Actions support
SmhiAlertCard.prototype._onRowAction = function (e, item) {
  // Only trigger card action when clicking outside the toggle link
  const tag = (e.composedPath?.()[0]?.tagName || '').toLowerCase();
  if (tag === 'ha-markdown' || (e.target && e.target.classList && e.target.classList.contains('details-toggle'))) {
    return;
  }
  const action = this.config?.tap_action || { action: 'more-info' };
  this._runAction(action, item);
};

SmhiAlertCard.prototype._runAction = function (action, item) {
  const a = action?.action || 'more-info';
  if (a === 'none') return;
  if (a === 'more-info') {
    const ev = new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId: this.config.entity } });
    this.dispatchEvent(ev);
    return;
  }
  if (a === 'navigate' && action.navigation_path) {
    history.pushState(null, '', action.navigation_path);
    const ev = new Event('location-changed', { bubbles: true, composed: true });
    this.dispatchEvent(ev);
    return;
  }
  if (a === 'url' && action.url_path) {
    window.open(action.url_path, '_blank');
    return;
  }
  if (a === 'call-service' && action.service) {
    const [domain, service] = action.service.split('.');
    this.hass.callService(domain, service, action.service_data || {});
    return;
  }
};
