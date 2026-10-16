{
const state = {
  map: null,
  mapSource: "domestic",
  mapTileLayer: null,
  aircraftMarkers: new Map(),
  receiverMarkers: new Map(),
  trackLayer: null,
  trackPositions: [],
  detailMap: null,
  detailTileLayer: null,
  detailAircraftMarker: null,
  detailRouteLayer: null,
  detailRouteAirportMarkers: [],
  didInitialFit: false,
  mapInteracting: false,
  mapRenderQueued: false,
  flightAnimationFrame: null,
  lastFlightFrameAt: 0,
  serverClockOffsetMs: 0,
  activeSeconds: 90,
  live: [],
  receivers: [],
  historyPage: 1,
  historyPageSize: 50,
  historyTotal: 0,
  search: "",
  selectedIcao: null,
  detailAircraft: null,
  quickAircraftIcao: null,
  quickEnrichments: new Map(),
  quickEnrichmentRefreshTimer: null,
  messageCursor: null,
  detailHours: 24,
  enrichmentRefreshTimer: null,
  socket: null,
  socketRetryTimer: null,
  socketRetryAttempt: 0,
  socketStopped: false,
  kioskMode: false,
  radioClickCooldowns: new Map(),
};

const elements = {
  statusDot: document.querySelector("#status-dot"),
  statusText: document.querySelector("#status-text"),
  lastUpdate: document.querySelector("#last-update"),
  liveList: document.querySelector("#live-list"),
  liveCount: document.querySelector("#live-count"),
  historyBody: document.querySelector("#history-body"),
  historyRange: document.querySelector("#history-range"),
  historyPrev: document.querySelector("#history-prev"),
  historyNext: document.querySelector("#history-next"),
  drawer: document.querySelector("#aircraft-drawer"),
  drawerBackdrop: document.querySelector("#drawer-backdrop"),
  drawerTitle: document.querySelector("#drawer-title"),
  drawerContent: document.querySelector("#drawer-content"),
  toast: document.querySelector("#toast"),
  mapQuickCard: document.querySelector("#map-quick-card"),
  kioskStats: document.querySelector("#kiosk-stats"),
  kioskClose: document.querySelector("#kiosk-close"),
};

const numberFormatter = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });
const fullNumberFormatter = new Intl.NumberFormat("zh-CN");
const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const browserLanguage = (navigator.languages?.[0] || navigator.language || "en").toLowerCase();

const AIRLINE_NAMES_ZH = Object.freeze({
  AAL: "美国航空",
  ACA: "加拿大航空",
  AFR: "法国航空",
  AAR: "韩亚航空",
  ANA: "全日空航空",
  AUA: "奥地利航空",
  BAW: "英国航空",
  CAL: "中华航空",
  CBG: "北部湾航空",
  CBJ: "首都航空",
  CCA: "中国国际航空",
  CDG: "山东航空",
  CDC: "长龙航空",
  CES: "中国东方航空",
  CGN: "长安航空",
  CHB: "西部航空",
  CHH: "海南航空",
  CJX: "江西航空",
  CKK: "中国货运航空",
  CPA: "国泰航空",
  CQH: "春秋航空",
  CSC: "四川航空",
  CSN: "中国南方航空",
  CSZ: "深圳航空",
  CUA: "中国联合航空",
  CUH: "乌鲁木齐航空",
  CXA: "厦门航空",
  CYZ: "中国邮政航空",
  DAL: "达美航空",
  DKH: "吉祥航空",
  DLH: "汉莎航空",
  EPA: "东海航空",
  ETD: "阿提哈德航空",
  EVA: "长荣航空",
  EZY: "易捷航空",
  FDX: "联邦快递航空",
  FIN: "芬兰航空",
  FZA: "福州航空",
  GCR: "天津航空",
  HBH: "河北航空",
  HXA: "华夏航空",
  ITY: "意大利航空",
  JAL: "日本航空",
  KAL: "大韩航空",
  KLM: "荷兰皇家航空",
  KNA: "昆明航空",
  LKE: "祥鹏航空",
  MAS: "马来西亚航空",
  OKA: "奥凯航空",
  QDA: "青岛航空",
  QFA: "澳洲航空",
  QTR: "卡塔尔航空",
  RLH: "瑞丽航空",
  RYR: "瑞安航空",
  SAS: "北欧航空",
  SIA: "新加坡航空",
  SWR: "瑞士国际航空",
  TBA: "西藏航空",
  THA: "泰国国际航空",
  THY: "土耳其航空",
  UAE: "阿联酋航空",
  UAL: "美国联合航空",
  UEA: "成都航空",
  UPS: "联合包裹航空",
  VIR: "维珍大西洋航空",
  YZR: "金鹏航空",
});

const AIRPORTS_ZH = Object.freeze({
  BKK: ["曼谷", "曼谷素万那普机场"],
  CAN: ["广州", "广州白云国际机场"],
  CDG: ["巴黎", "巴黎夏尔·戴高乐机场"],
  CGO: ["郑州", "郑州新郑国际机场"],
  CGQ: ["长春", "长春龙嘉国际机场"],
  CKG: ["重庆", "重庆江北国际机场"],
  CSX: ["长沙", "长沙黄花国际机场"],
  CTU: ["成都", "成都双流国际机场"],
  DLC: ["大连", "大连周水子国际机场"],
  DOH: ["多哈", "多哈哈马德国际机场"],
  DXB: ["迪拜", "迪拜国际机场"],
  FRA: ["法兰克福", "法兰克福机场"],
  FOC: ["福州", "福州长乐国际机场"],
  FUO: ["佛山", "佛山沙堤机场"],
  HAK: ["海口", "海口美兰国际机场"],
  HET: ["呼和浩特", "呼和浩特白塔国际机场"],
  HFE: ["合肥", "合肥新桥国际机场"],
  HGH: ["杭州", "杭州萧山国际机场"],
  HKG: ["香港", "香港国际机场"],
  HND: ["东京", "东京羽田机场"],
  HRB: ["哈尔滨", "哈尔滨太平国际机场"],
  HUZ: ["惠州", "惠州平潭机场"],
  ICN: ["首尔", "首尔仁川国际机场"],
  JFK: ["纽约", "纽约肯尼迪国际机场"],
  KHH: ["高雄", "高雄国际机场"],
  KIX: ["大阪", "大阪关西国际机场"],
  KMG: ["昆明", "昆明长水国际机场"],
  KUL: ["吉隆坡", "吉隆坡国际机场"],
  KWE: ["贵阳", "贵阳龙洞堡国际机场"],
  KWL: ["桂林", "桂林两江国际机场"],
  LAX: ["洛杉矶", "洛杉矶国际机场"],
  LHR: ["伦敦", "伦敦希思罗机场"],
  LHW: ["兰州", "兰州中川国际机场"],
  LXA: ["拉萨", "拉萨贡嘎国际机场"],
  MFM: ["澳门", "澳门国际机场"],
  MXZ: ["梅州", "梅州梅县机场"],
  NGB: ["宁波", "宁波栎社国际机场"],
  NKG: ["南京", "南京禄口国际机场"],
  NNG: ["南宁", "南宁吴圩国际机场"],
  NRT: ["东京", "东京成田国际机场"],
  PEK: ["北京", "北京首都国际机场"],
  PKX: ["北京", "北京大兴国际机场"],
  PVG: ["上海", "上海浦东国际机场"],
  SHA: ["上海", "上海虹桥国际机场"],
  SHE: ["沈阳", "沈阳桃仙国际机场"],
  SIN: ["新加坡", "新加坡樟宜机场"],
  SFO: ["旧金山", "旧金山国际机场"],
  SJW: ["石家庄", "石家庄正定国际机场"],
  SWA: ["揭阳", "揭阳潮汕国际机场"],
  SYD: ["悉尼", "悉尼金斯福德·史密斯机场"],
  SYX: ["三亚", "三亚凤凰国际机场"],
  SZX: ["深圳", "深圳宝安国际机场"],
  TAO: ["青岛", "青岛胶东国际机场"],
  TFU: ["成都", "成都天府国际机场"],
  TNA: ["济南", "济南遥墙国际机场"],
  TPE: ["台北", "台湾桃园国际机场"],
  TSA: ["台北", "台北松山机场"],
  TSN: ["天津", "天津滨海国际机场"],
  TYN: ["太原", "太原武宿国际机场"],
  URC: ["乌鲁木齐", "乌鲁木齐地窝堡国际机场"],
  WNZ: ["温州", "温州龙湾国际机场"],
  WUH: ["武汉", "武汉天河国际机场"],
  WUX: ["无锡", "苏南硕放国际机场"],
  XIY: ["西安", "西安咸阳国际机场"],
  XMN: ["厦门", "厦门高崎国际机场"],
  YNT: ["烟台", "烟台蓬莱国际机场"],
  ZHA: ["湛江", "湛江吴川机场"],
  ZUH: ["珠海", "珠海金湾机场"],
});

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtTime(ms) {
  return ms ? timeFormatter.format(new Date(ms)) : "—";
}

function ago(ms, now = Date.now()) {
  if (!ms) return "未知";
  const seconds = Math.max(0, Math.round((now - ms) / 1000));
  if (seconds < 60) return `${seconds} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function altitude(value) {
  if (value === null || value === undefined) return "—";
  if (Number(value) === 0) return "地面";
  return `${fullNumberFormatter.format(value)} ft`;
}

function speed(value) {
  return value === null || value === undefined ? "—" : `${Math.round(value)} kt`;
}

function heading(value) {
  return value === null || value === undefined ? "—" : `${Math.round(value)}°`;
}

function finiteCoordinatePair(latitude, longitude) {
  const lat = Number(latitude);
  const lon = Number(longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return [lat, lon];
}

function flightNumbers(aircraft) {
  const icao = String(aircraft.route_callsign_icao || aircraft.callsign || "").trim().toUpperCase() || null;
  let iata = String(aircraft.route_callsign_iata || "").trim().toUpperCase() || null;
  const airlineIcao = String(aircraft.airline_icao || "").trim().toUpperCase();
  const airlineIata = String(aircraft.airline_iata || "").trim().toUpperCase();
  if (!iata && icao && airlineIcao && airlineIata && icao.startsWith(airlineIcao)) {
    iata = `${airlineIata}${icao.slice(airlineIcao.length)}`;
  }
  return { iata, icao };
}

function flightLabel(aircraft) {
  const numbers = flightNumbers(aircraft);
  const labels = [numbers.iata, numbers.icao].filter((value, index, items) => value && items.indexOf(value) === index);
  return labels.join(" / ") || aircraft.registration || `ICAO ${aircraft.icao}`;
}

function aircraftModelLabel(aircraft) {
  const makerAndModel = [aircraft.aircraft_manufacturer, aircraft.aircraft_model].filter(Boolean).join(" ");
  return makerAndModel || aircraft.aircraft_type || "机型资料查询中";
}

function aircraftDescription(aircraft) {
  const model = aircraftModelLabel(aircraft);
  return model === "机型资料查询中" ? (aircraft.registration || "机型待补全") : model;
}

function localizedAirlineName(aircraft) {
  const sourceName = aircraft.airline_name || null;
  if (!browserLanguage.startsWith("zh")) return sourceName;
  const icao = String(aircraft.airline_icao || "").trim().toUpperCase();
  return AIRLINE_NAMES_ZH[icao] || sourceName;
}

function airlineLabel(aircraft) {
  const name = localizedAirlineName(aircraft);
  if (!name) return "航司待补全";
  const code = [aircraft.airline_iata, aircraft.airline_icao].filter(Boolean).join(" / ");
  return code ? `${name} (${code})` : name;
}

function airportCode(aircraft, prefix) {
  return aircraft[`${prefix}_iata`] || aircraft[`${prefix}_icao`] || "—";
}

function localizedAirportData(aircraft, prefix) {
  if (!browserLanguage.startsWith("zh")) return null;
  return AIRPORTS_ZH[airportCode(aircraft, prefix).toUpperCase()] || null;
}

function localizedAirportDetail(aircraft, prefix) {
  const localized = localizedAirportData(aircraft, prefix);
  if (localized) return localized[1];
  return [
    aircraft[`${prefix}_city`],
    aircraft[`${prefix}_name`],
    aircraft[`${prefix}_country`],
  ].filter((value, index, items) => value && items.indexOf(value) === index).join(" · ");
}

function airportShortLabel(aircraft, prefix) {
  const code = airportCode(aircraft, prefix);
  const localized = localizedAirportData(aircraft, prefix);
  const city = localized?.[0] || aircraft[`${prefix}_city`];
  return city ? `${code} ${city}` : code;
}

function routeShort(aircraft) {
  if (![aircraft.origin_name, aircraft.origin_iata, aircraft.origin_icao,
    aircraft.destination_name, aircraft.destination_iata, aircraft.destination_icao].some(Boolean)) return "";
  return `${airportShortLabel(aircraft, "origin")} → ${airportShortLabel(aircraft, "destination")}`;
}

function quickCardMode() {
  if (state.kioskMode) return true;
  return window.matchMedia("(max-width: 720px)").matches
    || window.matchMedia("(pointer: coarse)").matches;
}

function setKioskMode(enabled) {
  state.kioskMode = enabled;
  document.body.classList.toggle("kiosk-map", enabled);
}

function hideAircraftQuickCard() {
  window.clearTimeout(state.quickEnrichmentRefreshTimer);
  if (state.quickAircraftIcao) {
    state.aircraftMarkers.get(state.quickAircraftIcao)?.getElement()?.classList.remove("is-quick-selected");
  }
  state.quickAircraftIcao = null;
  elements.mapQuickCard.hidden = true;
  elements.mapQuickCard.innerHTML = "";
}

function renderAircraftQuickCard() {
  if (!state.quickAircraftIcao) return;
  const liveAircraft = state.live.find((item) => item.icao === state.quickAircraftIcao);
  if (!liveAircraft) {
    hideAircraftQuickCard();
    return;
  }
  const aircraft = { ...liveAircraft, ...(state.quickEnrichments.get(state.quickAircraftIcao) || {}) };
  const airlineName = localizedAirlineName(aircraft) || aircraft.registered_owner;
  const airlineLoading = !airlineName && enrichmentPending(aircraft);
  const airlineText = airlineName || (airlineLoading ? "航司资料查询中" : "航司资料暂无记录");
  const model = aircraftModelLabel(aircraft);
  const route = routeShort(aircraft);
  const registration = aircraft.registration || aircraft.metadata_registration || "注册号待补全";
  const statusItems = [
    `高度 ${altitude(aircraft.altitude_baro)}`,
    `速度 ${speed(aircraft.ground_speed)}`,
    `航向 ${heading(aircraft.track)}`,
    aircraft.squawk ? `应答 ${aircraft.squawk}` : null,
  ].filter(Boolean);
  elements.mapQuickCard.innerHTML = `
    <div class="quick-card-heading">
      <div>
        <strong>${escapeHtml(flightLabel(aircraft))}</strong>
        <span class="mono">${escapeHtml(aircraft.icao)}</span>
      </div>
      <button type="button" data-quick-close aria-label="关闭快速信息">×</button>
    </div>
    <div class="quick-card-identification">
      <b class="${airlineLoading ? "is-loading" : ""}">${airlineLoading ? "<i></i>" : ""}${escapeHtml(airlineText)}</b>
      <span>${escapeHtml(registration)} · ${escapeHtml(model)}</span>
    </div>
    ${route ? `<div class="quick-card-route">${escapeHtml(route)}</div>` : ""}
    <div class="quick-card-footer">
      ${statusItems.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
      <button type="button" data-quick-detail>详细资料</button>
    </div>`;
  elements.mapQuickCard.hidden = false;
}

async function refreshQuickCardEnrichment(icao) {
  const aircraft = state.live.find((item) => item.icao === icao);
  if (!aircraft) return;
  try {
    const data = await api(enrichmentUrl(icao, aircraft.callsign));
    const enrichedAircraft = { ...aircraft, ...(state.quickEnrichments.get(icao) || {}), ...(data.aircraft || {}) };
    state.quickEnrichments.set(icao, data.aircraft || {});
    if (state.quickAircraftIcao === icao) {
      renderAircraftQuickCard();
      if (enrichmentPending(enrichedAircraft)) scheduleQuickEnrichmentRefresh(icao, 1);
    }
  } catch (_error) {
    scheduleQuickEnrichmentRefresh(icao, 1);
  }
}

function scheduleQuickEnrichmentRefresh(icao, attempt = 0) {
  window.clearTimeout(state.quickEnrichmentRefreshTimer);
  if (attempt >= 6 || state.quickAircraftIcao !== icao) return;
  const delay = [250, 600, 1000, 1600, 2400, 3500][attempt];
  state.quickEnrichmentRefreshTimer = window.setTimeout(async () => {
    if (state.quickAircraftIcao !== icao) return;
    const aircraft = state.live.find((item) => item.icao === icao);
    if (!aircraft) return;
    try {
      const data = await api(enrichmentUrl(icao, aircraft.callsign));
      if (state.quickAircraftIcao !== icao) return;
      const enrichedAircraft = { ...aircraft, ...(state.quickEnrichments.get(icao) || {}), ...(data.aircraft || {}) };
      state.quickEnrichments.set(icao, data.aircraft || {});
      renderAircraftQuickCard();
      if (enrichmentPending(enrichedAircraft)) scheduleQuickEnrichmentRefresh(icao, attempt + 1);
    } catch (_error) {
      scheduleQuickEnrichmentRefresh(icao, attempt + 1);
    }
  }, delay);
}

function showAircraftQuickCard(icao) {
  window.clearTimeout(state.quickEnrichmentRefreshTimer);
  state.aircraftMarkers.get(state.quickAircraftIcao)?.getElement()?.classList.remove("is-quick-selected");
  state.quickAircraftIcao = icao;
  state.aircraftMarkers.get(icao)?.getElement()?.classList.add("is-quick-selected");
  renderAircraftQuickCard();
  refreshQuickCardEnrichment(icao);
}

function enrichmentPending(aircraft) {
  const metadataPending = aircraft.metadata_status === null || aircraft.metadata_status === undefined;
  const routePending = Boolean(aircraft.callsign) && (aircraft.route_status === null || aircraft.route_status === undefined);
  return metadataPending || routePending;
}

function enrichmentUrl(icao, callsign = null) {
  const params = new URLSearchParams();
  const cleanedCallsign = String(callsign || "").trim().toUpperCase();
  if (cleanedCallsign) params.set("callsign", cleanedCallsign);
  const query = params.toString();
  return `/api/v1/aircraft/${icao}/enrichment${query ? `?${query}` : ""}`;
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`请求失败 (${response.status})`);
  return response.json();
}

async function playAircraftRadio(icao) {
  const now = Date.now();
  const lastPlayedAt = state.radioClickCooldowns.get(icao) || 0;
  if (now - lastPlayedAt < 2500) return;
  state.radioClickCooldowns.set(icao, now);
  try {
    const response = await fetch(`/api/v1/aircraft/${icao}/radio`, { method: "POST" });
    if (!response.ok && response.status !== 503) {
      console.warn("Aircraft radio playback failed", response.status);
    }
  } catch (error) {
    console.warn("Aircraft radio playback skipped", error);
  }
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => elements.toast.classList.remove("show"), 3000);
}

function setConnection(online, text) {
  elements.statusDot.className = `pulse-dot ${online ? "online" : "offline"}`;
  elements.statusText.textContent = text;
}

const GCJ_A = 6378245.0;
const GCJ_EE = 0.006693421622965943;

function outsideGcjChina(latitude, longitude) {
  return longitude < 72.004 || longitude > 137.8347 || latitude < 0.8293 || latitude > 55.8271;
}

function transformGcjLatitude(x, y) {
  let value = -100 + (2 * x) + (3 * y) + (0.2 * y * y) + (0.1 * x * y) + (0.2 * Math.sqrt(Math.abs(x)));
  value += ((20 * Math.sin(6 * x * Math.PI)) + (20 * Math.sin(2 * x * Math.PI))) * 2 / 3;
  value += ((20 * Math.sin(y * Math.PI)) + (40 * Math.sin(y / 3 * Math.PI))) * 2 / 3;
  value += ((160 * Math.sin(y / 12 * Math.PI)) + (320 * Math.sin(y * Math.PI / 30))) * 2 / 3;
  return value;
}

function transformGcjLongitude(x, y) {
  let value = 300 + x + (2 * y) + (0.1 * x * x) + (0.1 * x * y) + (0.1 * Math.sqrt(Math.abs(x)));
  value += ((20 * Math.sin(6 * x * Math.PI)) + (20 * Math.sin(2 * x * Math.PI))) * 2 / 3;
  value += ((20 * Math.sin(x * Math.PI)) + (40 * Math.sin(x / 3 * Math.PI))) * 2 / 3;
  value += ((150 * Math.sin(x / 12 * Math.PI)) + (300 * Math.sin(x / 30 * Math.PI))) * 2 / 3;
  return value;
}

function wgs84ToGcj02(latitude, longitude) {
  if (outsideGcjChina(latitude, longitude)) return [latitude, longitude];
  let latitudeOffset = transformGcjLatitude(longitude - 105, latitude - 35);
  let longitudeOffset = transformGcjLongitude(longitude - 105, latitude - 35);
  const radians = latitude / 180 * Math.PI;
  let magic = Math.sin(radians);
  magic = 1 - (GCJ_EE * magic * magic);
  const squareRoot = Math.sqrt(magic);
  latitudeOffset = latitudeOffset * 180 / ((GCJ_A * (1 - GCJ_EE) / (magic * squareRoot)) * Math.PI);
  longitudeOffset = longitudeOffset * 180 / ((GCJ_A / squareRoot * Math.cos(radians)) * Math.PI);
  return [latitude + latitudeOffset, longitude + longitudeOffset];
}

function gcj02ToWgs84(latitude, longitude) {
  if (outsideGcjChina(latitude, longitude)) return [latitude, longitude];
  let wgsLatitude = latitude;
  let wgsLongitude = longitude;
  for (let iteration = 0; iteration < 6; iteration += 1) {
    const converted = wgs84ToGcj02(wgsLatitude, wgsLongitude);
    wgsLatitude -= converted[0] - latitude;
    wgsLongitude -= converted[1] - longitude;
  }
  return [wgsLatitude, wgsLongitude];
}

function mapDisplayPosition(latitude, longitude, source = state.mapSource) {
  return source === "domestic" ? wgs84ToGcj02(latitude, longitude) : [latitude, longitude];
}

function createMapTileLayer(source) {
  const commonOptions = {
    maxZoom: 18,
    updateWhenZooming: true,
    updateWhenIdle: false,
    updateInterval: 120,
    keepBuffer: 4,
  };
  if (source === "international") {
    return L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      ...commonOptions,
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>',
    });
  }
  return L.tileLayer("https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}", {
    ...commonOptions,
    subdomains: "1234",
    attribution: '&copy; <a href="https://www.amap.com/" target="_blank" rel="noopener noreferrer">高德地图</a>',
  });
}

function updateMapSourceButton() {
  const button = document.querySelector("#map-source-toggle");
  const international = state.mapSource === "international";
  button.textContent = international ? "底图：OSM" : "底图：高德";
  button.setAttribute("aria-pressed", String(international));
  button.title = international ? "切换到国内高德地图" : "切换到国际 OpenStreetMap";
}

function switchMapSource() {
  if (!state.map) return;
  const previousSource = state.mapSource;
  const currentCenter = state.map.getCenter();
  const centerWgs84 = previousSource === "domestic"
    ? gcj02ToWgs84(currentCenter.lat, currentCenter.lng)
    : [currentCenter.lat, currentCenter.lng];
  const zoom = state.map.getZoom();
  state.mapSource = previousSource === "domestic" ? "international" : "domestic";
  state.mapTileLayer?.remove();
  state.mapTileLayer = createMapTileLayer(state.mapSource).addTo(state.map);
  if (state.detailMap) {
    state.detailTileLayer?.remove();
    state.detailTileLayer = createMapTileLayer(state.mapSource).addTo(state.detailMap);
  }
  state.map.setView(mapDisplayPosition(...centerWgs84), zoom, { animate: false });

  state.aircraftMarkers.forEach((marker) => {
    if (marker.skySimulatedWgs84) marker.setLatLng(mapDisplayPosition(...marker.skySimulatedWgs84));
  });
  state.receiverMarkers.forEach((marker) => {
    if (marker.skyWgs84) marker.setLatLng(mapDisplayPosition(...marker.skyWgs84));
  });
  if (state.trackPositions.length) drawTrack(state.trackPositions, false);
  updateMapSourceButton();
  try {
    window.localStorage.setItem("skytrace-map-source", state.mapSource);
  } catch (_error) {
    // Map switching still works when browser storage is disabled.
  }
  showToast(state.mapSource === "international"
    ? "已切换到国际 OpenStreetMap（部分国内网络可能较慢）"
    : "已切换到国内高德地图");
}

function initMap() {
  if (!window.L) {
    document.querySelector("#map").hidden = true;
    document.querySelector("#map-unavailable").hidden = false;
    return;
  }
  const mapElement = document.querySelector("#map");
  try {
    if (window.localStorage.getItem("skytrace-map-source") === "international") {
      state.mapSource = "international";
    }
  } catch (_error) {
    // Use the domestic default when browser storage is disabled.
  }
  state.map = L.map(mapElement, {
    zoomControl: true,
    preferCanvas: true,
    dragging: true,
    scrollWheelZoom: true,
    touchZoom: true,
    doubleClickZoom: true,
    boxZoom: true,
    keyboard: true,
    zoomSnap: 0.5,
    zoomDelta: 0.5,
    zoomAnimation: true,
    fadeAnimation: true,
    markerZoomAnimation: false,
    inertia: false,
    bounceAtZoomLimits: false,
    wheelDebounceTime: 40,
    wheelPxPerZoomLevel: 120,
  }).setView(mapDisplayPosition(22.65, 113.5), 7);
  state.mapTileLayer = createMapTileLayer(state.mapSource).addTo(state.map);
  updateMapSourceButton();

  state.map.dragging.enable();
  state.map.scrollWheelZoom.enable();
  state.map.touchZoom.enable();

  // Re-enable input handlers before Leaflet handles the same event. This also
  // protects the map from browser lifecycle edge cases on mobile.
  mapElement.addEventListener("pointerdown", () => {
    if (!state.map.dragging.enabled()) state.map.dragging.enable();
  }, { capture: true, passive: true });
  mapElement.addEventListener("wheel", () => {
    if (!state.map.scrollWheelZoom.enabled()) state.map.scrollWheelZoom.enable();
  }, { capture: true, passive: true });

  let interactionEndTimer;
  let zoomTransitionTimer;
  const beginInteraction = () => {
    window.clearTimeout(interactionEndTimer);
    state.mapInteracting = true;
    mapElement.classList.add("map-is-interacting");
  };
  const endInteraction = () => {
    window.clearTimeout(interactionEndTimer);
    interactionEndTimer = window.setTimeout(() => {
      state.mapInteracting = false;
      mapElement.classList.remove("map-is-interacting");
      mapElement.dataset.zoom = String(state.map.getZoom());
      scheduleMapRender();
    }, 0);
  };
  const beginZoom = () => {
    window.clearTimeout(zoomTransitionTimer);
    mapElement.classList.add("map-is-zooming");
    beginInteraction();
  };
  const endZoom = () => {
    endInteraction();
    window.clearTimeout(zoomTransitionTimer);
    // Keep position transitions disabled until Leaflet finishes reprojecting
    // every marker for the final zoom level. Repeated wheel input resets this.
    zoomTransitionTimer = window.setTimeout(() => {
      mapElement.classList.remove("map-is-zooming");
    }, 160);
  };
  state.map.on("movestart", beginInteraction);
  state.map.on("moveend", endInteraction);
  state.map.on("zoomstart", beginZoom);
  state.map.on("zoomend", endZoom);
  state.map.on("click", hideAircraftQuickCard);
  mapElement.dataset.zoom = String(state.map.getZoom());
  state.flightAnimationFrame = window.requestAnimationFrame(animateFlights);
}

function planeIcon(aircraft, extraClass = "") {
  const rotation = Number(aircraft.track || 0);
  return L.divIcon({
    className: `aircraft-marker${extraClass ? ` ${extraClass}` : ""}`,
    html: `
      <span class="plane-marker" style="--plane-heading:${rotation}deg" aria-hidden="true">
        <svg class="plane-shape" viewBox="0 0 1024 1024" focusable="false">
          <path d="M922.6 698.6v-74.7l-335.9-224V138.6S586.7 64 512 64s-74.7 74.6-74.7 74.6v261.3L101.4 624v74.7l335.9-112v209.1l-112 89.6V960L512 885.3l186.6 74.6v-74.6l-112-89.6V586.6l336 112z"></path>
        </svg>
      </span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function updatePlaneMarkerHeading(marker, aircraft) {
  const element = marker?.getElement();
  const plane = element?.querySelector(".plane-marker");
  if (plane) plane.style.setProperty("--plane-heading", `${Number(aircraft.track || 0)}deg`);
}

function unwrapHeading(previous, next) {
  const normalizedPrevious = ((previous % 360) + 360) % 360;
  const shortestDelta = ((next - normalizedPrevious + 540) % 360) - 180;
  return previous + shortestDelta;
}

const EARTH_RADIUS_METERS = 6371008.8;

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function destinationPoint(latitude, longitude, track, distanceMeters) {
  if (!distanceMeters || !Number.isFinite(track)) return [latitude, longitude];
  const angularDistance = distanceMeters / EARTH_RADIUS_METERS;
  const bearing = track * Math.PI / 180;
  const latitudeRadians = latitude * Math.PI / 180;
  const longitudeRadians = longitude * Math.PI / 180;
  const targetLatitude = Math.asin(
    (Math.sin(latitudeRadians) * Math.cos(angularDistance))
    + (Math.cos(latitudeRadians) * Math.sin(angularDistance) * Math.cos(bearing)),
  );
  const targetLongitude = longitudeRadians + Math.atan2(
    Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(latitudeRadians),
    Math.cos(angularDistance) - (Math.sin(latitudeRadians) * Math.sin(targetLatitude)),
  );
  return [
    targetLatitude * 180 / Math.PI,
    ((targetLongitude * 180 / Math.PI + 540) % 360) - 180,
  ];
}

function motionFromAircraft(aircraft, previous = null) {
  const track = Number(aircraft.track);
  return {
    latitude: Number(aircraft.latitude),
    longitude: Number(aircraft.longitude),
    observedAt: Number(aircraft.position_at_ms || aircraft.last_seen_ms || 0),
    speedMps: Math.max(0, Number(aircraft.ground_speed || 0)) * 0.514444,
    track: Number.isFinite(track) ? ((track % 360) + 360) % 360 : null,
    updateIntervalMs: previous?.updateIntervalMs || 5000,
    correction: previous?.correction || null,
  };
}

function predictAircraftPosition(motion, nowMs) {
  const predictionLimit = clamp(motion.updateIntervalMs * 3, 8000, 20000);
  const elapsedMs = clamp(nowMs - motion.observedAt, 0, predictionLimit);
  const predicted = destinationPoint(
    motion.latitude,
    motion.longitude,
    motion.track,
    motion.speedMps * elapsedMs / 1000,
  );

  if (!motion.correction) return predicted;
  const progress = clamp((nowMs - motion.correction.startedAt) / motion.correction.duration, 0, 1);
  const remaining = 1 - ((progress * progress) * (3 - (2 * progress)));
  predicted[0] += motion.correction.latitudeOffset * remaining;
  predicted[1] += motion.correction.longitudeOffset * remaining;
  if (progress >= 1) motion.correction = null;
  return predicted;
}

function updateAircraftMotion(marker, aircraft, nowMs) {
  const previous = marker.skyMotion;
  const next = motionFromAircraft(aircraft, previous);
  if (!previous) {
    marker.skyMotion = next;
    marker.skySimulatedWgs84 = predictAircraftPosition(next, nowMs);
    marker.setLatLng(mapDisplayPosition(...marker.skySimulatedWgs84));
    return;
  }
  if (next.observedAt < previous.observedAt) return;

  const reportInterval = next.observedAt - previous.observedAt;
  if (reportInterval > 0) {
    next.updateIntervalMs = clamp(reportInterval, 1000, 15000);
    next.correction = null;
    const currentPosition = marker.skySimulatedWgs84 || predictAircraftPosition(previous, nowMs);
    const newPrediction = predictAircraftPosition(next, nowMs);
    const correctionDistance = L.latLng(currentPosition).distanceTo(L.latLng(newPrediction));
    const expectedDistance = Math.max(250, next.speedMps * reportInterval / 1000);
    const mustSnap = reportInterval > 30000 || correctionDistance > Math.max(20000, expectedDistance * 6);

    if (mustSnap) {
      marker.skySimulatedWgs84 = newPrediction;
      marker.setLatLng(mapDisplayPosition(...newPrediction));
    } else {
      next.correction = {
        latitudeOffset: currentPosition[0] - newPrediction[0],
        longitudeOffset: currentPosition[1] - newPrediction[1],
        startedAt: nowMs,
        duration: clamp(next.updateIntervalMs * 0.9, 850, 2600),
      };
    }
  }
  marker.skyMotion = next;
}

function flightFrameInterval(zoom) {
  if (zoom >= 13) return 1000 / 45;
  if (zoom >= 10) return 1000 / 30;
  if (zoom >= 7) return 50;
  return 80;
}

function animateFlights(frameTime) {
  state.flightAnimationFrame = window.requestAnimationFrame(animateFlights);
  if (!state.map || state.mapInteracting || document.hidden) return;
  const mapElement = state.map.getContainer();
  if (mapElement.classList.contains("map-is-zooming")) return;

  const zoom = state.map.getZoom();
  if (frameTime - state.lastFlightFrameAt < flightFrameInterval(zoom)) return;
  state.lastFlightFrameAt = frameTime;
  const nowMs = Date.now() + state.serverClockOffsetMs;
  const markerTtlMs = Math.min(state.activeSeconds * 1000, 75_000);

  state.aircraftMarkers.forEach((marker, key) => {
    if (marker.skyLastSeenMs && nowMs - marker.skyLastSeenMs > markerTtlMs) {
      marker.remove();
      state.aircraftMarkers.delete(key);
      if (state.quickAircraftIcao === key) hideAircraftQuickCard();
      return;
    }
    if (!marker.skyMotion) return;
    const nextWgs84 = predictAircraftPosition(marker.skyMotion, nowMs);
    if (!finiteCoordinatePair(nextWgs84[0], nextWgs84[1])) return;
    const nextDisplayPosition = L.latLng(mapDisplayPosition(...nextWgs84));
    const currentDisplayPosition = marker.getLatLng();
    const pixelDistance = state.map.project(currentDisplayPosition, zoom)
      .distanceTo(state.map.project(nextDisplayPosition, zoom));
    if (pixelDistance < 0.03) return;
    marker.setLatLng(nextDisplayPosition);
    marker.skySimulatedWgs84 = nextWgs84;
  });
}

function renderMap() {
  if (!state.map || state.mapInteracting || document.hidden) return;
  const currentAircraft = new Set();
  const bounds = [];
  const simulationNow = Date.now() + state.serverClockOffsetMs;
  const aircraftTtlMs = Math.min(state.activeSeconds * 1000, 75_000);
  state.live.forEach((aircraft) => {
    const position = finiteCoordinatePair(aircraft.latitude, aircraft.longitude);
    if (!position) return;
    if (simulationNow - Number(aircraft.last_seen_ms || 0) > aircraftTtlMs) return;
    const key = aircraft.icao;
    currentAircraft.add(key);
    const latLng = mapDisplayPosition(...position);
    bounds.push(latLng);
    let marker = state.aircraftMarkers.get(key);
    if (!marker) {
      marker = L.marker(latLng, {
        icon: planeIcon(aircraft),
        keyboard: true,
        bubblingMouseEvents: false,
      }).addTo(state.map);
      marker.skyTrack = Number(aircraft.track || 0);
      marker.skyHeading = marker.skyTrack;
      updateAircraftMotion(marker, aircraft, simulationNow);
      marker.on("click", () => {
        playAircraftRadio(key);
        if (quickCardMode()) showAircraftQuickCard(key);
        else openAircraft(key);
      });
      marker.bindTooltip("", { direction: "top", offset: [0, -13], className: "sky-tooltip" });
      state.aircraftMarkers.set(key, marker);
    } else {
      updateAircraftMotion(marker, aircraft, simulationNow);
      const nextTrack = Number(aircraft.track || 0);
      if (marker.skyTrack !== nextTrack) {
        marker.skyHeading = unwrapHeading(marker.skyHeading, nextTrack);
        marker.getElement()?.querySelector(".plane-marker")?.style.setProperty("--plane-heading", `${marker.skyHeading}deg`);
        marker.skyTrack = nextTrack;
      }
    }
    marker.skyLastSeenMs = Number(aircraft.last_seen_ms || 0);
    const tooltipLines = [
      `<strong>${escapeHtml(flightLabel(aircraft))}</strong>`,
      `${escapeHtml(aircraft.icao)} · ${escapeHtml(altitude(aircraft.altitude_baro))}`,
    ];
    const airlineName = localizedAirlineName(aircraft);
    if (airlineName) tooltipLines.push(escapeHtml(airlineName));
    if (routeShort(aircraft)) tooltipLines.push(escapeHtml(routeShort(aircraft)));
    const tooltip = tooltipLines.join("<br>");
    if (marker.skyTooltip !== tooltip) {
      marker.setTooltipContent(tooltip);
      marker.skyTooltip = tooltip;
    }
  });
  state.aircraftMarkers.forEach((marker, key) => {
    if (!currentAircraft.has(key)) {
      marker.remove();
      state.aircraftMarkers.delete(key);
    }
  });
  if (state.quickAircraftIcao && !currentAircraft.has(state.quickAircraftIcao)) hideAircraftQuickCard();

  const currentReceivers = new Set();
  state.receivers.forEach((receiver) => {
    const position = finiteCoordinatePair(receiver.latitude, receiver.longitude);
    if (!position) return;
    currentReceivers.add(receiver.id);
    const latLng = mapDisplayPosition(...position);
    bounds.push(latLng);
    let marker = state.receiverMarkers.get(receiver.id);
    if (!marker) {
      const icon = L.divIcon({
        className: "",
        html: '<span class="receiver-marker" aria-hidden="true"></span>',
        iconSize: [15, 15],
        iconAnchor: [7, 7],
      });
      marker = L.marker(latLng, { icon }).addTo(state.map);
      marker.skyPosition = latLng;
      marker.skyWgs84 = position;
      marker.bindTooltip(escapeHtml(receiver.name), { direction: "top", className: "sky-tooltip" });
      state.receiverMarkers.set(receiver.id, marker);
    } else {
      if (marker.skyPosition?.[0] !== latLng[0] || marker.skyPosition?.[1] !== latLng[1]) {
        marker.setLatLng(latLng);
        marker.skyPosition = latLng;
        marker.skyWgs84 = position;
      }
    }
  });
  state.receiverMarkers.forEach((marker, key) => {
    if (!currentReceivers.has(key)) {
      marker.remove();
      state.receiverMarkers.delete(key);
    }
  });

  if (!state.didInitialFit && bounds.length) {
    state.map.fitBounds(bounds, { padding: [45, 45], maxZoom: 9, animate: false });
    state.didInitialFit = true;
  }
}

function scheduleMapRender() {
  if (state.mapRenderQueued) return;
  state.mapRenderQueued = true;
  window.requestAnimationFrame(() => {
    state.mapRenderQueued = false;
    renderMap();
  });
}

function fitMap() {
  if (!state.map) return;
  const points = [
    ...state.live.map((a) => finiteCoordinatePair(a.latitude, a.longitude)).filter(Boolean).map((position) => mapDisplayPosition(...position)),
    ...state.receivers.map((r) => finiteCoordinatePair(r.latitude, r.longitude)).filter(Boolean).map((position) => mapDisplayPosition(...position)),
  ];
  if (points.length) {
    state.map.stop();
    state.map.fitBounds(points, { padding: [45, 45], maxZoom: 10, animate: false });
  }
}

function renderLiveList(serverNow) {
  const visibleAircraft = state.live.filter((aircraft) => serverNow - Number(aircraft.last_seen_ms || 0) <= Math.min(state.activeSeconds * 1000, 75_000));
  elements.liveCount.textContent = visibleAircraft.length;
  if (!visibleAircraft.length) {
    elements.liveList.innerHTML = `
      <div class="empty-state compact">
        <span class="radar-loader"></span>
        <p>最近 90 秒没有收到飞机信号</p>
      </div>`;
    return;
  }
  elements.liveList.innerHTML = visibleAircraft
    .map(
      (aircraft) => `
      <button class="contact-card" type="button" data-icao="${escapeHtml(aircraft.icao)}">
        <span>
          <span class="contact-title">
            <strong>${escapeHtml(flightLabel(aircraft))}</strong>
            <span class="mono">${escapeHtml(aircraft.icao)}</span>
          </span>
          <span class="contact-enrichment">
            ${escapeHtml(localizedAirlineName(aircraft) || aircraft.registered_owner || "公开资料待补全")}
            <i>·</i>
            ${escapeHtml(aircraft.aircraft_type || aircraft.aircraft_model || "机型未知")}
            ${routeShort(aircraft) ? `<i>·</i> ${escapeHtml(routeShort(aircraft))}` : ""}
          </span>
          <span class="contact-meta">
            <span>${escapeHtml(speed(aircraft.ground_speed))}</span>
            <span>航向 ${escapeHtml(heading(aircraft.track))}</span>
            <span>${aircraft.latitude === null ? "位置待解" : "位置已定位"}</span>
          </span>
        </span>
        <span class="contact-aside">
          <strong>${escapeHtml(altitude(aircraft.altitude_baro))}</strong>
          <small>${escapeHtml(ago(aircraft.last_seen_ms, serverNow))}</small>
        </span>
      </button>`,
    )
    .join("");
}

function renderStats(data) {
  if (!data) return;
  document.querySelector("#stat-active").textContent = fullNumberFormatter.format(data.active_aircraft);
  document.querySelector("#stat-total").textContent = fullNumberFormatter.format(data.total_aircraft);
  document.querySelector("#stat-messages").textContent = numberFormatter.format(data.messages_24h);
  document.querySelector("#stat-receivers").textContent = `${data.online_receivers}/${data.total_receivers}`;
  if (elements.kioskStats) {
    elements.kioskStats.textContent = `当前 ${fullNumberFormatter.format(data.active_aircraft)} · 历史 ${fullNumberFormatter.format(data.total_aircraft)} · 报文 ${numberFormatter.format(data.messages_24h)} · 接收站 ${data.online_receivers}/${data.total_receivers}`;
  }
}

function applyLiveSnapshot(message) {
  const data = message.live;
  if (!data || !Array.isArray(data.aircraft) || !Array.isArray(data.receivers)) return;
  state.serverClockOffsetMs = data.server_now_ms - Date.now();
  state.activeSeconds = data.active_seconds;
  state.live = data.aircraft.filter((aircraft) => data.server_now_ms - Number(aircraft.last_seen_ms || 0) <= Math.min(data.active_seconds * 1000, 75_000));
  state.receivers = data.receivers;
  if (state.quickAircraftIcao) renderAircraftQuickCard();
  renderLiveList(data.server_now_ms);
  renderStats(message.stats);
  scheduleMapRender();
  if (state.selectedIcao) {
    const selectedAircraft = state.live.find((aircraft) => aircraft.icao === state.selectedIcao);
    if (selectedAircraft) {
      try {
        const detailAircraft = { ...(state.detailAircraft || {}), ...selectedAircraft };
        state.detailAircraft = detailAircraft;
        updateDetailSummary(detailAircraft);
        updateDetailMap(detailAircraft, true);
      } catch (error) {
        console.warn("Detail map update skipped", error);
      }
    }
  }
  const online = data.receivers.some((receiver) => data.server_now_ms - receiver.last_seen_ms <= data.active_seconds * 1000);
  setConnection(online, online ? "接收站在线 · 实时" : "接收站离线 · 实时");
  elements.lastUpdate.textContent = `WebSocket 实时更新 ${fmtTime(data.server_now_ms)}`;
  document.querySelector("#receiver-name").textContent = data.receivers[0]?.name || "等待树莓派";
}

function liveSocketUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/v1/live`;
}

function selectNearestVisibleAircraft() {
  if (!state.map) return;
  const bounds = state.map.getBounds();
  const centerPoint = state.map.getSize().divideBy(2);
  let nearest = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  state.live.forEach((aircraft) => {
    const marker = state.aircraftMarkers.get(aircraft.icao);
    if (!marker) return;
    const markerPosition = marker.getLatLng();
    if (!bounds.contains(markerPosition)) return;
    const distance = state.map.latLngToContainerPoint(markerPosition).distanceTo(centerPoint);
    if (distance < nearestDistance) {
      nearest = aircraft.icao;
      nearestDistance = distance;
    }
  });
  if (nearest) showAircraftQuickCard(nearest);
  else showToast("当前视野没有飞机");
}

function handleHardwareControl(message) {
  if (!state.map || !document.querySelector("#view-live")?.classList.contains("is-active")) return;
  if (message.action === "pan") {
    const x = Math.max(-1, Math.min(1, Number(message.x) || 0));
    const y = Math.max(-1, Math.min(1, Number(message.y) || 0));
    state.map.panBy([x * 22, y * 22], { animate: false });
  } else if (message.action === "zoom") {
    const delta = Math.max(-8, Math.min(8, Math.trunc(Number(message.delta) || 0)));
    if (delta) state.map.setZoom(state.map.getZoom() + delta, { animate: false });
  } else if (message.action === "select_nearest") {
    selectNearestVisibleAircraft();
  }
}

function connectLiveSocket() {
  window.clearTimeout(state.socketRetryTimer);
  if (state.socketStopped || state.socket?.readyState === WebSocket.OPEN || state.socket?.readyState === WebSocket.CONNECTING) return;

  setConnection(false, "正在连接实时数据");
  elements.lastUpdate.textContent = "正在建立 WebSocket 连接…";
  const socket = new WebSocket(liveSocketUrl());
  state.socket = socket;

  socket.addEventListener("open", () => {
    if (socket !== state.socket) return;
    state.socketRetryAttempt = 0;
  });
  socket.addEventListener("message", (event) => {
    if (socket !== state.socket) return;
    try {
      const message = JSON.parse(event.data);
      if (message.type === "snapshot") applyLiveSnapshot(message);
      else if (message.type === "hardware_control") handleHardwareControl(message);
    } catch (_error) {
      showToast("收到无法识别的实时数据");
    }
  });
  socket.addEventListener("error", () => socket.close());
  socket.addEventListener("close", () => {
    if (socket !== state.socket) return;
    state.socket = null;
    if (state.socketStopped) return;
    setConnection(false, "实时连接中断");
    const delay = Math.min(15000, 1000 * (2 ** state.socketRetryAttempt));
    state.socketRetryAttempt += 1;
    elements.lastUpdate.textContent = `${Math.ceil(delay / 1000)} 秒后自动重连…`;
    state.socketRetryTimer = window.setTimeout(connectLiveSocket, delay);
  });
}

function switchView(name) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("is-active", view.id === `view-${name}`));
  document.querySelectorAll(".nav-button").forEach((button) => button.classList.toggle("is-active", button.dataset.view === name));
  if (name === "history") loadHistory();
  if (name !== "live") hideAircraftQuickCard();
  if (name === "live" && state.map) window.setTimeout(() => state.map.invalidateSize({ pan: false, animate: false }), 50);
  window.location.hash = state.kioskMode && name === "live" ? "live-kiosk" : name;
}

async function loadHistory() {
  elements.historyBody.innerHTML = '<tr><td colspan="6">正在载入历史档案…</td></tr>';
  try {
    const params = new URLSearchParams({
      search: state.search,
      page: state.historyPage,
      page_size: state.historyPageSize,
    });
    const data = await api(`/api/v1/aircraft?${params}`);
    state.historyTotal = data.total;
    if (!data.items.length) {
      elements.historyBody.innerHTML = '<tr><td colspan="6">没有匹配的飞机记录</td></tr>';
    } else {
      elements.historyBody.innerHTML = data.items
        .map(
          (aircraft) => `
          <tr>
            <td class="aircraft-cell">
              <strong>${escapeHtml(flightLabel(aircraft))}</strong>
              <small class="mono">${escapeHtml(aircraft.icao)}</small>
              <span class="aircraft-secondary">${escapeHtml(localizedAirlineName(aircraft) || aircraft.registered_owner || "资料待补全")} · ${escapeHtml(aircraft.aircraft_type || aircraft.aircraft_model || "机型未知")}</span>
            </td>
            <td data-label="最后信号">${escapeHtml(fmtTime(aircraft.last_seen_ms))}<br><small>${escapeHtml(ago(aircraft.last_seen_ms))}</small></td>
            <td data-label="高度">${escapeHtml(altitude(aircraft.altitude_baro))}</td>
            <td data-label="速度 / 航向">${escapeHtml(speed(aircraft.ground_speed))} / ${escapeHtml(heading(aircraft.track))}</td>
            <td data-label="累计报文" class="mono">${fullNumberFormatter.format(aircraft.messages_received)}</td>
            <td><button class="table-action" type="button" data-icao="${escapeHtml(aircraft.icao)}">详情</button></td>
          </tr>`,
        )
        .join("");
    }
    const from = data.total ? (data.page - 1) * data.page_size + 1 : 0;
    const to = Math.min(data.total, data.page * data.page_size);
    elements.historyRange.textContent = `显示 ${from}–${to}，共 ${fullNumberFormatter.format(data.total)} 架`;
    elements.historyPrev.disabled = data.page <= 1;
    elements.historyNext.disabled = to >= data.total;
  } catch (error) {
    elements.historyBody.innerHTML = `<tr><td colspan="6">${escapeHtml(error.message)}</td></tr>`;
  }
}

function enrichmentMarkup(aircraft) {
  const hasAircraftData = Boolean(
    aircraft.aircraft_manufacturer || aircraft.aircraft_model || aircraft.aircraft_type ||
    aircraft.registration || aircraft.registered_owner,
  );
  const hasRoute = Boolean(aircraft.origin_name || aircraft.destination_name);
  const aircraftLoading = !hasAircraftData && (aircraft.metadata_status === null || aircraft.metadata_status === undefined);
  const routeLoading = Boolean(aircraft.callsign) && !hasRoute && (aircraft.route_status === null || aircraft.route_status === undefined);
  const aircraftEmptyText = aircraft.metadata_status === "not_found"
    ? "公开资料库暂未收录这架飞机"
    : aircraft.metadata_status === "error"
      ? "资料源暂时不可用，服务端会自动重试"
      : "正在后台查询飞机注册与机型资料";
  const routeEmptyText = !aircraft.callsign
    ? "报文中还没有稳定的航班呼号，无法匹配航线"
    : aircraft.route_status === "not_found"
      ? "公开资料库暂未收录这个呼号的航线"
      : aircraft.route_status === "error"
        ? "航线资料源暂时不可用，服务端会自动重试"
        : "正在后台查询航司与计划航线";
  const originDetail = localizedAirportDetail(aircraft, "origin");
  const destinationDetail = localizedAirportDetail(aircraft, "destination");
  const airlineName = localizedAirlineName(aircraft);
  const numbers = flightNumbers(aircraft);

  return `
    <section id="aircraft-enrichment" class="detail-section enrichment-section">
      <div class="detail-section-heading">
        <h4>航班与飞机资料</h4>
        <a class="source-link" href="https://www.adsbdb.com/" target="_blank" rel="noopener noreferrer">资料源 ADSBDB ↗</a>
      </div>
      <div class="enrichment-grid">
        <article class="enrichment-card">
          <span class="card-kicker">AIRCRAFT</span>
          ${hasAircraftData ? `
            <strong>${escapeHtml(aircraftDescription(aircraft))}</strong>
            <dl class="info-rows">
              <div><dt>注册号</dt><dd class="mono">${escapeHtml(aircraft.registration || "—")}</dd></div>
              <div><dt>ICAO 机型码</dt><dd class="mono">${escapeHtml(aircraft.metadata_type_code || aircraft.aircraft_type || "—")}</dd></div>
              <div><dt>注册所有人</dt><dd>${escapeHtml(aircraft.registered_owner || "—")}</dd></div>
              <div><dt>注册国家</dt><dd>${escapeHtml(aircraft.registered_owner_country || "—")}</dd></div>
            </dl>` : aircraftLoading ? `<div class="enrichment-loading"><span></span><p>${escapeHtml(aircraftEmptyText)}</p></div>` : `<p class="enrichment-empty">${escapeHtml(aircraftEmptyText)}</p>`}
        </article>
        <article class="enrichment-card route-card">
          <span class="card-kicker">FLIGHT / ROUTE</span>
          ${airlineName ? `<strong>${escapeHtml(airlineLabel(aircraft))}</strong>` : `<strong>${escapeHtml(flightLabel(aircraft))}</strong>`}
          ${(numbers.iata || numbers.icao) ? `
            <dl class="info-rows flight-number-rows">
              <div><dt>旅客航班号</dt><dd class="mono">${escapeHtml(numbers.iata || "—")}</dd></div>
              <div><dt>ICAO / ADS-B</dt><dd class="mono">${escapeHtml(numbers.icao || "—")}</dd></div>
            </dl>` : ""}
          ${hasRoute ? `
            <div class="route-line" aria-label="公开资料中的计划航线">
              <div class="route-airport">
                <b class="mono">${escapeHtml(airportCode(aircraft, "origin"))}</b>
                <span>${escapeHtml(originDetail || "起飞机场")}</span>
              </div>
              <span class="route-arrow" aria-hidden="true">→</span>
              <div class="route-airport destination">
                <b class="mono">${escapeHtml(airportCode(aircraft, "destination"))}</b>
                <span>${escapeHtml(destinationDetail || "目的机场")}</span>
              </div>
            </div>` : routeLoading ? `<div class="enrichment-loading"><span></span><p>${escapeHtml(routeEmptyText)}</p></div>` : `<p class="enrichment-empty">${escapeHtml(routeEmptyText)}</p>`}
        </article>
      </div>
      <p class="data-caveat">航司、机型与航线按 ICAO 地址和呼号匹配公开资料。航线是计划/常见航线，不代表本次飞行的实时放行计划，请以航空公司或机场信息为准。</p>
    </section>`;
}

function coordinateVerificationMarkup(aircraft) {
  const latitude = Number(aircraft.latitude);
  const longitude = Number(aircraft.longitude);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    return `
      <section class="detail-section coordinate-section">
        <div class="detail-section-heading"><h4>坐标校验</h4><span class="mono">WGS-84 → GCJ-02</span></div>
        <p class="coordinate-empty">这架飞机暂时没有可用的 ADS-B 经纬度。</p>
      </section>`;
  }

  const displayPosition = wgs84ToGcj02(latitude, longitude);
  const offsetMeters = L.latLng(latitude, longitude).distanceTo(L.latLng(displayPosition));
  return `
    <section class="detail-section coordinate-section">
      <div class="detail-section-heading"><h4>坐标校验</h4><span class="mono">WGS-84 → GCJ-02</span></div>
      <div class="coordinate-grid">
        <article>
          <span>ADS-B 原始坐标</span>
          <strong class="mono">${latitude.toFixed(6)}, ${longitude.toFixed(6)}</strong>
          <small>数据库与 API 保存值 · 位置时间 ${escapeHtml(fmtTime(aircraft.position_at_ms || aircraft.last_seen_ms))}</small>
        </article>
        <article>
          <span>高德地图绘制坐标</span>
          <strong class="mono">${displayPosition[0].toFixed(6)}, ${displayPosition[1].toFixed(6)}</strong>
          <small>GCJ-02 显示偏移约 ${fullNumberFormatter.format(Math.round(offsetMeters))} 米</small>
        </article>
      </div>
      <p class="coordinate-note">实时动画以原始 ADS-B 坐标为锚点，根据地速、航向和报文时间短时外推；以上原始坐标不会被模拟位置覆盖。</p>
    </section>`;
}

function destroyDetailMap() {
  if (state.detailMap) {
    state.detailMap.remove();
    state.detailMap = null;
  }
  state.detailTileLayer = null;
  state.detailAircraftMarker = null;
  state.detailRouteLayer = null;
  state.detailRouteAirportMarkers = [];
}

function routePlanPoints(aircraft) {
  const currentLatitude = Number(aircraft.latitude);
  const currentLongitude = Number(aircraft.longitude);
  const destinationLatitude = Number(aircraft.destination_latitude);
  const destinationLongitude = Number(aircraft.destination_longitude);
  if (![currentLatitude, currentLongitude, destinationLatitude, destinationLongitude].every(Number.isFinite)) return null;
  return [
    mapDisplayPosition(currentLatitude, currentLongitude),
    mapDisplayPosition(destinationLatitude, destinationLongitude),
  ];
}

function airportDotIcon(label) {
  return L.divIcon({
    className: "detail-route-airport-marker",
    html: `<span>${escapeHtml(label)}</span>`,
    iconSize: [42, 18],
    iconAnchor: [21, 9],
  });
}

function updateDetailRoute(aircraft) {
  if (!state.detailMap) return;
  const points = routePlanPoints(aircraft);
  if (!points) return;
  if (state.detailRouteLayer) {
    state.detailRouteLayer.remove();
    state.detailRouteLayer = null;
  }
  state.detailRouteAirportMarkers.forEach((marker) => marker.remove());
  state.detailRouteAirportMarkers = [];

  state.detailRouteLayer = L.polyline(points, {
    color: "#6eb7ff",
    weight: 3,
    opacity: 0.92,
    interactive: false,
  }).addTo(state.detailMap);
  const destinationMarker = L.marker(points[1], {
    icon: airportDotIcon(airportCode(aircraft, "destination")),
    interactive: false,
  }).addTo(state.detailMap);
  state.detailRouteAirportMarkers = [destinationMarker];
}

function updateDetailMap(aircraft, follow = false) {
  const mapElement = document.querySelector("#detail-mini-map");
  const statusElement = document.querySelector("#detail-mini-map-status");
  if (!window.L || !mapElement) return;
  const position = finiteCoordinatePair(aircraft.latitude, aircraft.longitude);
  if (!position) {
    if (statusElement) statusElement.textContent = "暂无可用坐标";
    return;
  }

  const latLng = mapDisplayPosition(...position);
  if (!state.detailMap) {
    state.detailMap = L.map(mapElement, {
      zoomControl: false,
      attributionControl: false,
      dragging: true,
      scrollWheelZoom: false,
      touchZoom: true,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      zoomSnap: 0.5,
      zoomDelta: 0.5,
      zoomAnimation: true,
      fadeAnimation: true,
      markerZoomAnimation: false,
    }).setView(latLng, 10.5);
    state.detailTileLayer = createMapTileLayer(state.mapSource).addTo(state.detailMap);
    state.detailAircraftMarker = L.marker(latLng, {
      icon: planeIcon(aircraft, "detail-aircraft-marker"),
      interactive: false,
    }).addTo(state.detailMap);
    window.requestAnimationFrame(() => {
      state.detailMap?.invalidateSize(false);
      state.detailMap?.setView(latLng, 10.5, { animate: false });
    });
  } else {
    state.detailAircraftMarker?.setLatLng(latLng);
    updatePlaneMarkerHeading(state.detailAircraftMarker, aircraft);
    if (follow) {
      const zoom = Math.max(state.detailMap.getZoom(), 10.5);
      if (state.detailMap.getZoom() < 10.5) {
        state.detailMap.setView(latLng, zoom, { animate: true, duration: 0.7 });
      } else {
        state.detailMap.panTo(latLng, { animate: true, duration: 0.7, easeLinearity: 0.35, noMoveStart: true });
      }
    }
  }

  if (statusElement) {
    statusElement.textContent = `${altitude(aircraft.altitude_baro)} · ${speed(aircraft.ground_speed)} · 航向 ${heading(aircraft.track)}`;
  }
  updateDetailRoute(aircraft);
}

function detailMarkup(aircraft, positions) {
  return `
    <div class="detail-identity">
      <div><h3 id="detail-flight-label">${escapeHtml(flightLabel(aircraft))}</h3><p class="mono">${escapeHtml(aircraft.icao)}</p></div>
      <div class="last-seen">最后信号<br><span id="detail-last-seen">${escapeHtml(fmtTime(aircraft.last_seen_ms))}</span></div>
    </div>
    <div class="detail-metrics">
      <div class="detail-metric"><span>气压高度</span><strong id="detail-altitude">${escapeHtml(altitude(aircraft.altitude_baro))}</strong></div>
      <div class="detail-metric"><span>地速</span><strong id="detail-speed">${escapeHtml(speed(aircraft.ground_speed))}</strong></div>
      <div class="detail-metric"><span>航向</span><strong id="detail-heading">${escapeHtml(heading(aircraft.track))}</strong></div>
    </div>
    <section class="detail-mini-map-section" aria-label="当前飞机位置">
      <div id="detail-mini-map" class="detail-mini-map"></div>
      <div class="detail-mini-map-label">
        <strong>${escapeHtml(flightLabel(aircraft))}</strong>
        <span id="detail-mini-map-status">等待实时位置</span>
      </div>
    </section>
    ${coordinateVerificationMarkup(aircraft)}
    ${enrichmentMarkup(aircraft)}
    <section class="detail-section">
      <div class="detail-section-heading">
        <h4>实时模式</h4>
        <span class="mono">LIVE ONLY</span>
      </div>
      <div class="track-summary">
        <span>状态：<strong>内存实时</strong></span>
        <span>航迹：<strong>${positions.length ? fullNumberFormatter.format(positions.length) : "不保存"}</strong></span>
        <span>原始报文：<strong>不保存</strong></span>
        <span>延迟目标：<strong>约 1 秒</strong></span>
      </div>
    </section>`;
}

function updateDetailSummary(aircraft) {
  const updates = [
    ["#detail-flight-label", flightLabel(aircraft)],
    ["#detail-last-seen", fmtTime(aircraft.last_seen_ms)],
    ["#detail-altitude", altitude(aircraft.altitude_baro)],
    ["#detail-speed", speed(aircraft.ground_speed)],
    ["#detail-heading", heading(aircraft.track)],
  ];
  updates.forEach(([selector, value]) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  });
}

function renderMessages(items, append = false) {
  const list = document.querySelector("#messages-list");
  if (!list) return;
  const html = items.length
    ? items.map((message) => {
      const decoded = message.decoded || { summary: "暂无解析", fields: [], notes: [] };
      const fields = Array.isArray(decoded.fields) ? decoded.fields : [];
      const notes = Array.isArray(decoded.notes) ? decoded.notes : [];
      const integrity = decoded.integrity === true
        ? '<span class="decode-badge is-ok">CRC 通过</span>'
        : decoded.integrity === false
          ? '<span class="decode-badge is-warning">CRC 异常</span>'
          : '<span class="decode-badge">校验含地址叠加</span>';
      const fieldRows = fields.map((field) => `
        <tr>
          <td data-label="位 / 原始位" class="mono decoded-bits"><b>${escapeHtml(field.bits)}</b><code>${escapeHtml(field.raw)}</code></td>
          <td data-label="字段">${escapeHtml(field.name)}</td>
          <td data-label="解析值" class="mono decoded-value">${escapeHtml(field.value)}</td>
          <td data-label="含义">${escapeHtml(field.meaning)}</td>
        </tr>`).join("");
      return `
        <details class="message-row">
          <summary class="message-summary">
            <span class="message-summary-main">
              <time>${escapeHtml(fmtTime(message.received_at_ms))}</time>
              <strong>${escapeHtml(decoded.summary || "Mode S 报文")}</strong>
            </span>
            <span class="message-tags">
              ${integrity}
              <span class="decode-badge">DF ${message.df}${message.type_code === null ? "" : ` / TC ${message.type_code}`}</span>
            </span>
          </summary>
          <div class="message-decode">
            <div class="message-meta">
              <span>接收站 ${escapeHtml(message.receiver_id)}</span>
              <span>${message.signal === null || message.signal === undefined ? "信号强度未知" : `信号 ${escapeHtml(message.signal)} dBFS`}</span>
            </div>
            <div class="message-raw" title="原始十六进制报文">${escapeHtml(message.raw.match(/.{1,2}/g)?.join(" ") || message.raw)}</div>
            ${decoded.binary ? `<div class="message-binary"><span>二进制（每组 8 位）</span><code>${escapeHtml(decoded.binary)}</code></div>` : ""}
            ${fieldRows ? `
              <div class="decoded-table-wrap">
                <table class="decoded-table">
                  <thead><tr><th>位 / 原始位</th><th>字段</th><th>解析值</th><th>含义</th></tr></thead>
                  <tbody>${fieldRows}</tbody>
                </table>
              </div>` : ""}
            ${notes.length ? `<ul class="decode-notes">${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>` : ""}
          </div>
        </details>`;
    }).join("")
    : '<div class="message-row">该飞机暂时没有存储的原始报文</div>';
  if (append) list.insertAdjacentHTML("beforeend", html);
  else list.innerHTML = html;
}

async function loadMessages(append = false) {
  if (!state.selectedIcao) return;
  const params = new URLSearchParams({ limit: "40" });
  if (append && state.messageCursor) params.set("cursor", state.messageCursor);
  try {
    const data = await api(`/api/v1/aircraft/${state.selectedIcao}/messages?${params}`);
    renderMessages(data.items, append);
    state.messageCursor = data.next_cursor;
    const button = document.querySelector("#load-more-messages");
    if (button) button.hidden = !data.next_cursor;
  } catch (error) {
    renderMessages([]);
    showToast(error.message);
  }
}

function scheduleEnrichmentRefresh(icao, attempt = 0) {
  window.clearTimeout(state.enrichmentRefreshTimer);
  if (attempt >= 6 || state.selectedIcao !== icao) return;
  const delay = [250, 600, 1000, 1600, 2400, 3500][attempt];
  state.enrichmentRefreshTimer = window.setTimeout(async () => {
    if (state.selectedIcao !== icao) return;
    try {
      const data = await api(enrichmentUrl(icao, state.detailAircraft?.callsign));
      if (state.selectedIcao !== icao) return;
      const liveAircraft = state.live.find((item) => item.icao === icao) || {};
      const aircraft = { ...(state.detailAircraft || {}), ...liveAircraft, ...(data.aircraft || {}) };
      state.detailAircraft = aircraft;
      const panel = document.querySelector("#aircraft-enrichment");
      if (panel) panel.outerHTML = enrichmentMarkup(aircraft);
      elements.drawerTitle.textContent = flightLabel(aircraft);
      updateDetailMap(aircraft, false);
      if (enrichmentPending(aircraft)) scheduleEnrichmentRefresh(icao, attempt + 1);
    } catch (_error) {
      scheduleEnrichmentRefresh(icao, attempt + 1);
    }
  }, delay);
}

function drawTrack(positions, fit = true) {
  if (!state.map) return;
  state.trackPositions = positions;
  if (state.trackLayer) {
    state.trackLayer.remove();
    state.trackLayer = null;
  }
  const points = positions.map((position) => mapDisplayPosition(position.latitude, position.longitude));
  if (!points.length) return;
  state.trackLayer = L.polyline(points, {
    color: "#7cf0b2",
    weight: 3,
    opacity: 0.82,
    smoothFactor: 2,
    interactive: false,
  }).addTo(state.map);
  if (fit) {
    state.map.stop();
    state.map.fitBounds(state.trackLayer.getBounds(), { padding: [55, 55], maxZoom: 11, animate: false });
  }
}

async function openAircraft(icao, hours = state.detailHours) {
  hideAircraftQuickCard();
  window.clearTimeout(state.enrichmentRefreshTimer);
  state.selectedIcao = icao;
  state.detailHours = hours;
  state.messageCursor = null;
  elements.drawerBackdrop.hidden = false;
  elements.drawer.classList.add("is-open");
  elements.drawer.setAttribute("aria-hidden", "false");
  elements.drawerTitle.textContent = `飞机 ${icao}`;
  destroyDetailMap();
  elements.drawerContent.innerHTML = '<div class="empty-state"><span class="radar-loader"></span><p>正在读取飞机档案</p></div>';
  try {
    const data = await api(`/api/v1/aircraft/${icao}?hours=${hours}`);
    if (state.selectedIcao !== icao) return;
    state.detailAircraft = data.aircraft;
    elements.drawerTitle.textContent = flightLabel(data.aircraft);
    elements.drawerContent.innerHTML = detailMarkup(data.aircraft, data.positions);
    try {
      updateDetailMap(data.aircraft, true);
    } catch (error) {
      console.warn("Detail map init skipped", error);
    }
    drawTrack([], false);
    scheduleEnrichmentRefresh(icao);
  } catch (error) {
    elements.drawerContent.innerHTML = `<div class="empty-state"><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function closeDrawer() {
  window.clearTimeout(state.enrichmentRefreshTimer);
  elements.drawer.classList.remove("is-open");
  elements.drawer.setAttribute("aria-hidden", "true");
  elements.drawerBackdrop.hidden = true;
  state.selectedIcao = null;
  state.detailAircraft = null;
  destroyDetailMap();
  if (state.trackLayer) {
    state.trackLayer.remove();
    state.trackLayer = null;
  }
  state.trackPositions = [];
}

document.querySelectorAll(".nav-button").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
document.querySelector("#fit-map").addEventListener("click", fitMap);
document.querySelector("#map-source-toggle").addEventListener("click", switchMapSource);
document.querySelector("#drawer-close").addEventListener("click", closeDrawer);
elements.drawerBackdrop.addEventListener("click", closeDrawer);
elements.kioskClose.addEventListener("click", async () => {
  state.socketStopped = true;
  state.socket?.close(1000, "kiosk closed");
  elements.kioskClose.disabled = true;
  try {
    await fetch("/api/v1/kiosk/close", { method: "POST" });
  } catch (_error) {
    window.close();
  }
});
elements.mapQuickCard.addEventListener("click", (event) => {
  event.stopPropagation();
  if (event.target.closest("[data-quick-close]")) hideAircraftQuickCard();
  if (event.target.closest("[data-quick-detail]") && state.quickAircraftIcao) {
    openAircraft(state.quickAircraftIcao);
  }
});
elements.liveList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-icao]");
  if (button) {
    playAircraftRadio(button.dataset.icao);
    openAircraft(button.dataset.icao);
  }
});
elements.historyBody.addEventListener("click", (event) => {
  const button = event.target.closest("[data-icao]");
  if (button) {
    playAircraftRadio(button.dataset.icao);
    openAircraft(button.dataset.icao);
  }
});
elements.drawerContent.addEventListener("click", (event) => {
  const period = event.target.closest("[data-hours]");
  if (period && state.selectedIcao) openAircraft(state.selectedIcao, Number(period.dataset.hours));
  if (event.target.closest("#load-more-messages")) loadMessages(true);
});
elements.historyPrev.addEventListener("click", () => {
  state.historyPage = Math.max(1, state.historyPage - 1);
  loadHistory();
});
elements.historyNext.addEventListener("click", () => {
  state.historyPage += 1;
  loadHistory();
});

let searchTimer;
document.querySelector("#history-search").addEventListener("input", (event) => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    state.search = event.target.value;
    state.historyPage = 1;
    loadHistory();
  }, 250);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.selectedIcao) closeDrawer();
});

initMap();
const initialHash = window.location.hash;
setKioskMode(initialHash === "#live-kiosk");
const initialView = initialHash === "#history" ? "history" : "live";
switchView(initialView);
if (state.kioskMode && state.map) {
  window.setTimeout(() => {
    state.map.invalidateSize({ pan: false, animate: false });
    fitMap();
  }, 100);
}
connectLiveSocket();
window.addEventListener("online", connectLiveSocket);
window.addEventListener("beforeunload", () => {
  state.socketStopped = true;
  window.clearTimeout(state.socketRetryTimer);
  state.socket?.close(1000, "page closed");
});
}
