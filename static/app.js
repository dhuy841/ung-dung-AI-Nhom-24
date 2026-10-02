const state = { user: null, page: "dashboard", aiAction: "announcement" };
const authState = { mode: "login", email: "", pendingEmail: "" };
const titles = { dashboard: "Tổng quan", members: "Thành viên", activities: "Hoạt động", "my-activities": "Lịch sử của tôi", tasks: "Nhiệm vụ", announcements: "Thông báo", ai: "Trợ lý AI", profile: "Hồ sơ của tôi" };
const roleNames = { president: "Chủ nhiệm", lead: "Trưởng ban", member: "Thành viên" };
const canManage = () => state.user && state.user.role !== "member";

function requiresConfirmation(method, path) {
  if (method === "PATCH" && (
    path === "/profile" ||
    /^\/activities\/\d+$/.test(path) ||
    /^\/tasks\/\d+$/.test(path)
  )) return true;

  if (method !== "POST") return false;
  return [
    /^\/auth\/register\/verify$/,
    /^\/auth\/reset-password$/,
    /^\/profile\/email\/verify$/,
    /^\/profile\/verification\/confirm$/,
    /^\/departments$/,
    /^\/members$/,
    /^\/activities$/,
    /^\/activities\/\d+\/attendance$/,
    /^\/tasks$/,
    /^\/announcements$/
  ].some(pattern => pattern.test(path));
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  if (requiresConfirmation(method, path)) {
    if (!window.confirm("Bạn có chắc chắn muốn thực hiện thao tác này không?")) {
      throw new DOMException("Đã hủy thao tác.", "AbortError");
    }
  }
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Đã xảy ra lỗi.");
  if (method !== "GET" && !(method === "POST" && path.startsWith("/ai/"))) {
    notify(data.message || "Thao tác đã thành công.");
  }
  return data;
}
function notify(message, error = false) {
  if (message === "Đã hủy thao tác.") return;
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.toggle("error-toast", error);
  toast.classList.add("show");
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => toast.classList.remove("show"), 3000);
}
function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}
function formValues(form) { return Object.fromEntries(new FormData(form).entries()); }
function dateText(value) {
  if (!value) return "Chưa cập nhật";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
}
function setLoggedIn(user) {
  state.user = user;
  if (!user.email_verified) state.page = "profile";
  document.querySelector("#login-screen").classList.add("hidden");
  document.querySelector("#app-screen").classList.remove("hidden");
  document.querySelector("#user-name").textContent = user.full_name;
  document.querySelector("#user-role").textContent = roleNames[user.role] || user.role;
  document.querySelector("#user-avatar").textContent = user.full_name.slice(0, 1).toUpperCase();
  document.querySelector("#top-avatar").textContent = user.full_name.slice(0, 1).toUpperCase();
  document.querySelector("#today-label").textContent = new Intl.DateTimeFormat("vi-VN", { weekday: "short", day: "numeric", month: "long", year: "numeric" }).format(new Date());
  render();
}
function setLoggedOut() {
  state.user = null;
  authState.mode = "login";
  authState.email = "";
  authState.pendingEmail = "";
  document.querySelector("#app-screen").classList.add("hidden");
  document.querySelector("#login-screen").classList.remove("hidden");
  renderAuth();
}
function renderAuth() {
  const root = document.querySelector("#auth-content");
  if (!root) return;
  const forms = {
    login: `<p class="eyebrow">KHÔNG GIAN CÂU LẠC BỘ</p><h1>Chào mừng trở lại</h1><p class="muted">Đăng nhập để quản lý hoạt động và kết nối thành viên.</p>
      <form id="login-form" class="stack"><label>Tên đăng nhập hoặc email<input name="username" autocomplete="username" required placeholder="Ví dụ: admin"></label><label>Mật khẩu<input name="password" type="password" autocomplete="current-password" required placeholder="Nhập mật khẩu"></label><button class="button primary" type="submit">Đăng nhập <span>→</span></button><p id="auth-error" class="error" role="alert"></p></form>
      <div class="auth-links"><button type="button" data-auth-mode="forgot">Quên mật khẩu?</button><button type="button" data-auth-mode="register">Tạo tài khoản mới</button></div>`,
    register: `<p class="eyebrow">THAM GIA CLUBSPACE</p><h1>Tạo tài khoản</h1><p class="muted">Xác minh email để hoàn tất đăng ký.</p>
      <form id="register-form" class="stack"><label>Họ và tên<input name="full_name" required autocomplete="name"></label><label>Tên đăng nhập<input name="username" required minlength="3" maxlength="40" autocomplete="username"></label><label>Email<input name="email" required type="email" autocomplete="email" placeholder="ban@gmail.com"></label><label>Mật khẩu<input name="password" required type="password" minlength="8" autocomplete="new-password"></label><label>Xác nhận mật khẩu<input name="confirm_password" required type="password" minlength="8" autocomplete="new-password"></label><button class="button primary" type="submit">Gửi mã xác minh</button><p id="auth-error" class="error" role="alert"></p></form><div class="auth-links"><button type="button" data-auth-mode="login">Quay lại đăng nhập</button></div>`,
    "register-code": `<p class="eyebrow">XÁC MINH EMAIL</p><h1>Nhập mã xác nhận</h1><p class="muted">Mã 6 chữ số đã được gửi đến ${escapeHtml(authState.email)}. Mã có hiệu lực trong 10 phút.</p>
      <form id="register-verify-form" class="stack"><label>Mã xác nhận<input name="code" required inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code"></label><button class="button primary" type="submit">Xác minh và tạo tài khoản</button><p id="auth-error" class="error" role="alert"></p></form><div class="auth-links"><button type="button" data-auth-mode="register">Quay lại đăng ký</button></div>`,
    forgot: `<p class="eyebrow">KHÔI PHỤC TÀI KHOẢN</p><h1>Quên mật khẩu?</h1><p class="muted">Nhập email đã đăng ký để nhận mã xác nhận.</p>
      <form id="forgot-form" class="stack"><label>Email tài khoản<input name="email" type="email" required autocomplete="email"></label><button class="button primary" type="submit">Gửi mã xác nhận</button><p id="auth-error" class="error" role="alert"></p></form><div class="auth-links"><button type="button" data-auth-mode="login">Quay lại đăng nhập</button></div>`,
    "reset-code": `<p class="eyebrow">ĐẶT LẠI MẬT KHẨU</p><h1>Kiểm tra email</h1><p class="muted">Nếu email thuộc tài khoản, mã xác nhận đã được gửi tới ${escapeHtml(authState.email)}.</p>
      <form id="reset-form" class="stack"><label>Mã xác nhận<input name="code" required inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code"></label><label>Mật khẩu mới<input name="new_password" type="password" required minlength="8" autocomplete="new-password"></label><label>Xác nhận mật khẩu mới<input name="confirm_password" type="password" required minlength="8" autocomplete="new-password"></label><button class="button primary" type="submit">Đặt lại mật khẩu</button><p id="auth-error" class="error" role="alert"></p></form><div class="auth-links"><button type="button" data-auth-mode="login">Quay lại đăng nhập</button></div>`
  };
  root.innerHTML = forms[authState.mode] || forms.login;
}
function authError(error) {
  const element = document.querySelector("#auth-error");
  if (element && error.name !== "AbortError") element.textContent = error.message;
}
function bindAuth() {
  const root = document.querySelector("#auth-content");
  root.addEventListener("click", event => {
    const button = event.target.closest("[data-auth-mode]");
    if (!button) return;
    authState.mode = button.dataset.authMode;
    renderAuth();
  });
  root.addEventListener("submit", async event => {
    const form = event.target;
    event.preventDefault();
    const values = formValues(form);
    try {
      if (form.id === "login-form") {
        if (!values.username.trim() || !values.password) throw new Error("Hãy nhập đầy đủ tên đăng nhập/email và mật khẩu.");
        const user = await api("/login", { method: "POST", body: JSON.stringify(values) });
        setLoggedIn(user);
        return;
      }
      if (form.id === "register-form") {
        if (values.password !== values.confirm_password) throw new Error("Mật khẩu xác nhận không khớp.");
        authState.email = values.email.trim().toLowerCase();
        delete values.confirm_password;
        await api("/auth/register", { method: "POST", body: JSON.stringify(values) });
        authState.mode = "register-code";
        renderAuth();
        return;
      }
      if (form.id === "register-verify-form") {
        const user = await api("/auth/register/verify", { method: "POST", body: JSON.stringify({ email: authState.email, code: values.code }) });
        setLoggedIn(user);
        return;
      }
      if (form.id === "forgot-form") {
        authState.email = values.email.trim().toLowerCase();
        await api("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email: authState.email }) });
        authState.mode = "reset-code";
        renderAuth();
        return;
      }
      if (form.id === "reset-form") {
        if (values.new_password !== values.confirm_password) throw new Error("Mật khẩu xác nhận không khớp.");
        await api("/auth/reset-password", { method: "POST", body: JSON.stringify({ email: authState.email, code: values.code, new_password: values.new_password }) });
        authState.mode = "login";
        renderAuth();
      }
    } catch (error) { authError(error); }
  });
}
async function render() {
  document.querySelector("#page-name").textContent = titles[state.page];
  document.querySelectorAll(".nav-item").forEach(button => button.classList.toggle("active", button.dataset.page === state.page));
  const content = document.querySelector("#content");
  content.innerHTML = '<div class="empty">Đang tải dữ liệu…</div>';
  try {
    if (state.page === "dashboard") await renderDashboard(content);
    if (state.page === "members") await renderMembers(content);
    if (state.page === "activities") await renderActivities(content);
    if (state.page === "my-activities") await renderMyActivities(content);
    if (state.page === "tasks") await renderTasks(content);
    if (state.page === "announcements") await renderAnnouncements(content);
    if (state.page === "ai") renderAI(content);
    if (state.page === "profile") await renderProfile(content);
  } catch (error) { content.innerHTML = `<div class="panel error">${escapeHtml(error.message)}</div>`; }
}
function heading(title, subtitle, button = "") {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div>${button}</div>`;
}
async function renderDashboard(root) {
  const data = await api("/dashboard");
  const cards = [
    ["Thành viên", data.totals.members, "♙", "purple", "Tổng số thành viên"],
    ["Hoạt động", data.totals.activities, "◷", "green", "Hoạt động đã tạo"],
    ["Nhiệm vụ mở", data.totals.open_tasks, "☑", "orange", "Đang chờ hoàn thành"],
    ["Thông báo", data.totals.announcements, "◉", "blue", "Thông tin đã chia sẻ"]
  ];
  root.innerHTML = `<div class="welcome-row"><div><h1>Xin chào, ${escapeHtml(state.user.full_name.split(" ").slice(-1)[0])} 👋</h1><p>Cùng xem những gì đang diễn ra trong câu lạc bộ của bạn.</p></div><span class="date-chip">${new Intl.DateTimeFormat("vi-VN", { day: "numeric", month: "long", year: "numeric" }).format(new Date())}</span></div>
    <section class="stats-grid">${cards.map(c => `<article class="stat-card"><div class="stat-top">${c[0]}<span class="stat-icon ${c[3]}">${c[2]}</span></div><div class="stat-value">${c[1]}</div><div class="stat-note">${c[4]}</div></article>`).join("")}</section>
    <section class="dashboard-grid"><article class="panel"><div class="panel-head"><h3>Hoạt động gần đây</h3><button data-goto="activities">Xem tất cả →</button></div>${data.recent.length ? data.recent.map(a => `<div class="activity-row"><div class="activity-date"><b>${escapeHtml((a.starts_at || "").slice(8, 10) || "—")}</b>${escapeHtml((a.starts_at || "").slice(5, 7) || "")}</div><div class="activity-meta"><b>${escapeHtml(a.title)}</b><small>${escapeHtml(dateText(a.starts_at))}</small></div><span class="badge ${escapeHtml(a.status)}">${statusName(a.status)}</span></div>`).join("") : '<div class="empty">Chưa có hoạt động nào.</div>'}</article>
    <article class="panel"><div class="panel-head"><h3>Bắt đầu nhanh</h3></div><div class="activity-row"><span class="stat-icon purple">◷</span><div class="activity-meta"><b>Lên kế hoạch hoạt động</b><small>Tạo sự kiện và điểm danh thành viên</small></div><button class="button" data-goto="activities">Mở →</button></div><div class="activity-row"><span class="stat-icon green">✦</span><div class="activity-meta"><b>Nhờ AI hỗ trợ</b><small>Soạn tin, tóm tắt và gợi ý phân công</small></div><button class="button" data-goto="ai">Thử AI →</button></div></article></section>`;
}
function statusName(status) {
  return ({ planned: "Sắp diễn ra", ongoing: "Đang diễn ra", completed: "Hoàn thành", cancelled: "Đã hủy", todo: "Cần thực hiện", in_progress: "Đang làm", done: "Hoàn thành", present: "Có mặt", absent: "Vắng mặt", excused: "Có phép" })[status] || status;
}
function priorityName(priority) {
  return ({ normal: "Bình thường", important: "Quan trọng", urgent: "Khẩn cấp" })[priority] || "Bình thường";
}
async function renderProfile(root) {
  const [profile, departments] = await Promise.all([api("/profile"), api("/departments")]);
  root.innerHTML = `${heading("Hồ sơ của tôi", "Thông tin tài khoản và chỉnh sửa hồ sơ cá nhân.")}
  <div class="page-layout profile-layout">
    <section class="panel profile-summary">
      <div class="profile-summary-head"><div class="profile-large-avatar">${escapeHtml(profile.full_name.slice(0, 1).toUpperCase())}</div><div><h2>${escapeHtml(profile.full_name)}</h2><span class="role-tag">${escapeHtml(roleNames[profile.role])}</span></div></div>
      <div class="profile-info"><div><small>TÊN ĐĂNG NHẬP</small><b>${escapeHtml(profile.username)}</b></div><div><small>VAI TRÒ</small><b>${escapeHtml(roleNames[profile.role])}</b></div><div><small>BAN CHUYÊN MÔN</small><b>${escapeHtml(profile.department_name || "Chưa phân ban")}</b></div></div>
      <p class="profile-hint">Vai trò và tên đăng nhập do hệ thống quản lý, không thể chỉnh sửa tại đây.</p>
      <div class="profile-email"><small>${profile.email_verified ? "EMAIL ĐÃ XÁC MINH" : "EMAIL CHƯA XÁC MINH"}</small><b>${escapeHtml(profile.email || "Chưa có email")}</b>
        ${!profile.email_verified ? '<p class="profile-hint">Xác minh email để sử dụng các chức năng của câu lạc bộ.</p>' : ""}
        <form id="profile-email-form" class="form-grid"><label>${profile.email_verified ? "Email mới" : "Email tài khoản"}<input name="email" type="email" required value="${escapeHtml(profile.email_verified ? authState.pendingEmail : profile.email)}" ${(authState.pendingEmail || !profile.email_verified) ? "readonly" : ""}></label>${!profile.email_verified ? `<label>Mã xác nhận<input name="code" required inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code"></label><button class="button primary" type="submit" data-verify-email>Xác minh email</button><button class="button" type="button" data-resend-current>Gửi lại mã xác minh</button>` : authState.pendingEmail ? `<label>Mã xác nhận<input name="code" required inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code"></label><button class="button primary" type="submit" data-verify-email>Xác minh email mới</button>` : `<button class="button" type="submit">Gửi mã xác minh email mới</button>`}<p class="error" id="profile-email-error" role="alert"></p></form>
      </div>
    </section>
    <form class="form-card form-grid profile-form" id="profile-form">
      <h3>Chỉnh sửa hồ sơ</h3>
      <label>Họ và tên<input name="full_name" value="${escapeHtml(profile.full_name)}" required></label>
      <label>Ban chuyên môn<select name="department_id"><option value="">Chưa phân ban</option>${departments.map(d => `<option value="${d.id}" ${String(d.id) === String(profile.department_id) ? "selected" : ""}>${escapeHtml(d.name)}</option>`).join("")}</select></label>
      <label>Kỹ năng<input name="skills" value="${escapeHtml(profile.skills || "")}" placeholder="Ví dụ: thiết kế, viết nội dung"></label>
      <label>Lịch rảnh<input name="availability" value="${escapeHtml(profile.availability || "")}" placeholder="Ví dụ: cuối tuần, buổi tối"></label>
      <div class="password-section"><b>Đổi mật khẩu <small>(không bắt buộc)</small></b>
        <label>Mật khẩu hiện tại<input name="current_password" type="password" autocomplete="current-password"></label>
        <label>Mật khẩu mới<input name="new_password" type="password" minlength="8" autocomplete="new-password"></label>
        <label>Xác nhận mật khẩu mới<input name="confirm_password" type="password" minlength="8" autocomplete="new-password"></label>
      </div>
      <button class="button primary" type="submit">Lưu thay đổi</button>
    </form>
  </div>`;
  document.querySelector("#profile-form").addEventListener("submit", async event => {
    event.preventDefault();
    const formData = formValues(event.currentTarget);
    if (formData.new_password && formData.new_password !== formData.confirm_password) {
      notify("Mật khẩu xác nhận không khớp.", true);
      return;
    }
    if (formData.new_password && !formData.current_password) {
      notify("Nhập mật khẩu hiện tại để đổi mật khẩu.", true);
      return;
    }
    delete formData.confirm_password;
    const button = event.currentTarget.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const updated = await api("/profile", { method: "PATCH", body: JSON.stringify(formData) });
      state.user = { ...state.user, ...updated };
      document.querySelector("#user-name").textContent = updated.full_name;
      document.querySelector("#user-avatar").textContent = updated.full_name.slice(0, 1).toUpperCase();
      document.querySelector("#top-avatar").textContent = updated.full_name.slice(0, 1).toUpperCase();
      notify("Đã cập nhật hồ sơ.");
      render();
    } catch (error) {
      notify(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  document.querySelector("#profile-email-form").addEventListener("submit", async event => {
    event.preventDefault();
    const values = formValues(event.currentTarget);
    const errorElement = document.querySelector("#profile-email-error");
    errorElement.textContent = "";
    try {
      if (!profile.email_verified || event.submitter?.hasAttribute("data-verify-email")) {
        const endpoint = profile.email_verified ? "/profile/email/verify" : "/profile/verification/confirm";
        const result = await api(endpoint, { method: "POST", body: JSON.stringify({ email: authState.pendingEmail || profile.email, code: values.code }) });
        authState.pendingEmail = "";
        if (result.email_verified) state.user = { ...state.user, email_verified: true };
        render();
      } else {
        await api("/profile/email/request", { method: "POST", body: JSON.stringify({ email: values.email }) });
        authState.pendingEmail = values.email.trim().toLowerCase();
        render();
      }
    } catch (error) {
      if (error.name !== "AbortError") errorElement.textContent = error.message;
    }
  });
  document.querySelector("[data-resend-current]")?.addEventListener("click", async () => {
    const errorElement = document.querySelector("#profile-email-error");
    errorElement.textContent = "";
    try {
      await api("/profile/email/verification/request", { method: "POST", body: JSON.stringify({}) });
    } catch (error) {
      if (error.name !== "AbortError") errorElement.textContent = error.message;
    }
  });
}
async function renderMembers(root) {
  const members = await api("/members");
  const departments = await api("/departments");
  root.innerHTML = `${heading("Thành viên", "Hồ sơ, kỹ năng và thông tin ban chuyên môn.", state.user.role === "president" ? '<button class="button primary" data-scroll-form>+ Thêm thành viên</button>' : "")}
  <div class="page-layout"><section class="data-panel"><div class="data-panel-header">Danh sách thành viên <span class="badge">${members.length} người</span></div><div class="table-wrap"><table><thead><tr><th>HỌ VÀ TÊN</th><th>VAI TRÒ</th><th>BAN</th><th>KỸ NĂNG</th><th>LỊCH RẢNH</th><th>LỊCH SỬ</th></tr></thead><tbody>${members.map(m => `<tr><td><strong>${escapeHtml(m.full_name)}</strong><br>${escapeHtml(m.email)}</td><td><span class="role-tag">${roleNames[m.role]}</span></td><td>${escapeHtml(m.department_name || "—")}</td><td>${escapeHtml(m.skills || "—")}</td><td>${escapeHtml(m.availability || "—")}</td><td><button class="text-button" data-history="${m.id}">Xem lịch sử</button></td></tr>`).join("")}</tbody></table></div></section>
  ${state.user.role === "president" ? `<div class="side-stack"><form class="form-card form-grid" id="member-form"><h3>Thêm thành viên</h3><label>Họ và tên<input name="full_name" required></label><label>Tên đăng nhập<input name="username" required minlength="3" maxlength="40"></label><label>Mật khẩu tạm<input name="password" type="password" required minlength="8"></label><label>Email<input name="email" type="email" required></label><label>Vai trò<select name="role"><option value="member">Thành viên</option><option value="lead">Trưởng ban</option><option value="president">Chủ nhiệm</option></select></label><label>Ban chuyên môn<select name="department_id"><option value="">Chưa phân ban</option>${departments.map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("")}</select></label><label>Kỹ năng<input name="skills" placeholder="Ví dụ: thiết kế, viết nội dung"></label><label>Lịch rảnh<input name="availability" placeholder="Ví dụ: cuối tuần"></label><button class="button primary">Tạo hồ sơ</button></form>
  <form class="form-card form-grid" id="department-form"><h3>Thêm ban chuyên môn</h3><label>Tên ban<input name="name" required></label><label>Mô tả<textarea name="description"></textarea></label><button class="button primary">Tạo ban</button></form></div>` : ""}</div>
  <section class="data-panel" style="margin-top:16px"><div class="data-panel-header">Các ban chuyên môn</div><div class="table-wrap"><table><thead><tr><th>TÊN BAN</th><th>MÔ TẢ</th></tr></thead><tbody>${departments.map(d => `<tr><td><strong>${escapeHtml(d.name)}</strong></td><td>${escapeHtml(d.description || "—")}</td></tr>`).join("")}</tbody></table></div></section>`;
  document.querySelectorAll("[data-history]").forEach(button => button.addEventListener("click", async () => {
    try {
      const items = await api(`/members/${button.dataset.history}/history`);
      alert(items.length ? items.map(i => `${i.title} — ${statusName(i.attendance_status)} (${dateText(i.starts_at)})`).join("\n") : "Thành viên chưa có lịch sử điểm danh.");
    } catch (error) { notify(error.message, true); }
  }));
  bindForm("#member-form", "/members", "POST");
  bindForm("#department-form", "/departments", "POST");
}
async function renderActivities(root) {
  const activities = await api("/activities");
  const members = canManage() ? await api("/members") : [];
  root.innerHTML = `${heading("Hoạt động", "Theo dõi sự kiện và điểm danh thành viên.", canManage() ? '<button class="button primary" data-scroll-form>+ Tạo hoạt động</button>' : "")}
  <div class="page-layout"><section class="data-panel"><div class="data-panel-header">Danh sách hoạt động</div><div class="table-wrap"><table><thead><tr><th>TÊN HOẠT ĐỘNG</th><th>THỜI GIAN</th><th>ĐỊA ĐIỂM</th><th>TRẠNG THÁI</th><th>THAM DỰ</th><th>ĐIỂM DANH</th></tr></thead><tbody>${activities.map(a => `<tr><td><strong>${escapeHtml(a.title)}</strong><br>${escapeHtml(a.description)}</td><td>${escapeHtml(dateText(a.starts_at))}</td><td>${escapeHtml(a.location || "—")}</td><td>${canManage() ? `<select data-activity-status="${a.id}"><option value="planned" ${a.status === "planned" ? "selected" : ""}>Sắp diễn ra</option><option value="ongoing" ${a.status === "ongoing" ? "selected" : ""}>Đang diễn ra</option><option value="completed" ${a.status === "completed" ? "selected" : ""}>Hoàn thành</option><option value="cancelled" ${a.status === "cancelled" ? "selected" : ""}>Đã hủy</option></select>` : `<span class="badge ${escapeHtml(a.status)}">${statusName(a.status)}</span>`}</td><td>${a.attendee_count}</td><td>${state.user.role === "member" ? `<button class="text-button" data-checkin="${a.id}">Tự điểm danh</button>` : "—"}</td></tr>`).join("")}</tbody></table>${activities.length ? "" : '<div class="empty">Chưa có hoạt động nào.</div>'}</div></section>
  ${canManage() ? `<div class="side-stack"><form class="form-card form-grid" id="activity-form"><h3>Tạo hoạt động</h3><label>Tên hoạt động<input name="title" required></label><label>Mô tả<textarea name="description"></textarea></label><label>Thời gian<input name="starts_at" type="datetime-local"></label><label>Địa điểm<input name="location"></label><button class="button primary">Tạo hoạt động</button></form>
  <form class="form-card form-grid" id="attendance-form"><h3>Ghi nhận điểm danh</h3><label>Hoạt động<select name="activity_id" required>${activities.map(a => `<option value="${a.id}">${escapeHtml(a.title)}</option>`).join("")}</select></label><label>Thành viên<select name="user_id" required>${members.map(m => `<option value="${m.id}">${escapeHtml(m.full_name)}</option>`).join("")}</select></label><label>Trạng thái<select name="status"><option value="present">Có mặt</option><option value="absent">Vắng mặt</option><option value="excused">Có phép</option></select></label><button class="button primary" ${activities.length ? "" : "disabled"}>Lưu điểm danh</button></form></div>` : ""}</div>`;
  bindForm("#activity-form", "/activities", "POST");
  const attendanceForm = document.querySelector("#attendance-form");
  if (attendanceForm) attendanceForm.addEventListener("submit", async event => {
    event.preventDefault();
    const form = formValues(attendanceForm);
    try {
      await api(`/activities/${form.activity_id}/attendance`, { method: "POST", body: JSON.stringify({ user_id: Number(form.user_id), status: form.status }) });
      notify("Đã lưu điểm danh."); render();
    } catch (error) { notify(error.message, true); }
  });
  document.querySelectorAll("[data-activity-status]").forEach(select => select.addEventListener("change", async () => {
    try { await api(`/activities/${select.dataset.activityStatus}`, { method: "PATCH", body: JSON.stringify({ status: select.value }) }); notify("Đã cập nhật hoạt động."); }
    catch (error) { notify(error.message, true); render(); }
  }));
  document.querySelectorAll("[data-checkin]").forEach(button => button.addEventListener("click", async () => {
    try { await api(`/activities/${button.dataset.checkin}/attendance`, { method: "POST", body: JSON.stringify({ status: "present" }) }); notify("Đã ghi nhận điểm danh."); render(); }
    catch (error) { notify(error.message, true); }
  }));
}
async function renderMyActivities(root) {
  const activities = await api("/my-activities");
  root.innerHTML = `${heading("Lịch sử của tôi", "Theo dõi các hoạt động, địa điểm và trạng thái điểm danh cá nhân.")}
  <section class="data-panel"><div class="data-panel-header">Hoạt động của tôi <span class="badge">${activities.filter(item => item.attendance_status === "present").length} lần có mặt</span></div>
  <div class="table-wrap"><table><thead><tr><th>HOẠT ĐỘNG</th><th>THỜI GIAN</th><th>ĐỊA ĐIỂM</th><th>TRẠNG THÁI SỰ KIỆN</th><th>ĐIỂM DANH</th></tr></thead><tbody>
  ${activities.map(activity => {
    const attendance = activity.attendance_status || "not_checked";
    const attendanceLabel = attendance === "not_checked" ? "Chưa điểm danh" : statusName(attendance);
    return `<tr><td><strong>${escapeHtml(activity.title)}</strong><br>${escapeHtml(activity.description || "")}</td><td>${escapeHtml(dateText(activity.starts_at))}</td><td>${escapeHtml(activity.location || "Chưa cập nhật")}</td><td><span class="badge ${escapeHtml(activity.status)}">${statusName(activity.status)}</span></td><td><span class="badge attendance-${escapeHtml(attendance)}">${attendanceLabel}</span>${activity.checked_at ? `<small class="attendance-time"> · ${escapeHtml(activity.checked_at)}</small>` : ""}</td></tr>`;
  }).join("")}
  </tbody></table>${activities.length ? "" : '<div class="empty">Chưa có hoạt động nào được ghi nhận.</div>'}</div></section>`;
}
async function renderTasks(root) {
  const tasks = await api("/tasks");
  const [members, departments] = canManage() ? await Promise.all([api("/members"), api("/departments")]) : [[], []];
  root.innerHTML = `${heading("Nhiệm vụ", "Phân công công việc, theo dõi tiến độ và hạn hoàn thành.")}
  <section class="data-panel">${tasks.length ? tasks.map(t => `<div class="task-row"><div><strong>${escapeHtml(t.title)}</strong><small>${escapeHtml(t.description || "Không có mô tả")} · ${escapeHtml(t.assignee_name || "Chưa giao")}</small></div><span class="priority-badge priority-${escapeHtml(t.priority || "normal")}">${priorityName(t.priority)}</span><span class="due">Hạn: ${escapeHtml(dateText(t.due_date))}</span><select data-task="${t.id}" ${!canManage() && t.assigned_to !== state.user.id ? "disabled" : ""}><option value="todo" ${t.status === "todo" ? "selected" : ""}>Cần thực hiện</option><option value="in_progress" ${t.status === "in_progress" ? "selected" : ""}>Đang làm</option><option value="done" ${t.status === "done" ? "selected" : ""}>Hoàn thành</option></select>${canManage() ? `<select data-priority="${t.id}" aria-label="Mức ưu tiên"><option value="normal" ${t.priority === "normal" ? "selected" : ""}>Bình thường</option><option value="important" ${t.priority === "important" ? "selected" : ""}>Quan trọng</option><option value="urgent" ${t.priority === "urgent" ? "selected" : ""}>Khẩn cấp</option></select>` : ""}</div>`).join("") : '<div class="empty">Chưa có nhiệm vụ nào.</div>'}</section>
  ${canManage() ? `<form class="form-card form-grid" id="task-form" style="margin-top:15px"><h3>Giao nhiệm vụ mới</h3><label>Tên nhiệm vụ<input name="title" required></label><label>Mô tả<textarea name="description"></textarea></label><label>Giao cho<select name="assigned_to"><option value="">Chưa giao</option>${members.filter(m => m.role !== "president").map(m => `<option value="${m.id}">${escapeHtml(m.full_name)}</option>`).join("")}</select></label><label>Ban chuyên môn<select name="department_id"><option value="">Không chọn</option>${departments.map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join("")}</select></label><label>Mức độ ưu tiên<select name="priority"><option value="normal">Bình thường</option><option value="important">Quan trọng</option><option value="urgent">Khẩn cấp</option></select></label><label>Hạn hoàn thành<input name="due_date" type="date"></label><button class="button primary">Tạo nhiệm vụ</button></form>` : ""}`;
  bindForm("#task-form", "/tasks", "POST");
  document.querySelectorAll("[data-task]").forEach(select => select.addEventListener("change", async () => {
    try { await api(`/tasks/${select.dataset.task}`, { method: "PATCH", body: JSON.stringify({ status: select.value }) }); notify("Đã cập nhật tiến độ."); }
    catch (error) { notify(error.message, true); render(); }
  }));
  document.querySelectorAll("[data-priority]").forEach(select => select.addEventListener("change", async () => {
    try { await api(`/tasks/${select.dataset.priority}`, { method: "PATCH", body: JSON.stringify({ priority: select.value }) }); notify("Đã cập nhật mức ưu tiên."); render(); }
    catch (error) { notify(error.message, true); render(); }
  }));
}
async function renderAnnouncements(root) {
  const items = await api("/announcements");
  root.innerHTML = `${heading("Thông báo", "Chia sẻ thông tin và cập nhật mới nhất với thành viên.", canManage() ? '<button class="button primary" data-scroll-form>+ Soạn thông báo</button>' : "")}
  <div class="page-layout"><section class="data-panel"><div class="data-panel-header">Bảng tin CLB</div>${items.map(a => `<article class="announcement-card"><h4>${escapeHtml(a.title)}</h4><p>${escapeHtml(a.content)}</p><small>${escapeHtml(a.creator_name || "CLB")} · ${escapeHtml(dateText(a.created_at))}</small></article>`).join("")}${items.length ? "" : '<div class="empty">Chưa có thông báo nào.</div>'}</section>
  ${canManage() ? `<form class="form-card form-grid" id="announcement-form"><h3>Soạn thông báo</h3><label>Tiêu đề<input name="title" required></label><label>Nội dung<textarea name="content" required></textarea></label><button class="button primary">Đăng thông báo</button></form>` : ""}</div>`;
  bindForm("#announcement-form", "/announcements", "POST");
}
const aiDefinitions = {
  announcement: { label: "✉ Sinh thông báo", placeholder: "Tên hoạt động, thời gian, địa điểm và thông tin cần nhắc thành viên…" },
  summary: { label: "▤ Tóm tắt hoạt động", placeholder: "Nhập ghi chú hoạt động và phản hồi của thành viên…" },
  assignment: { label: "♧ Gợi ý phân công", placeholder: "Mô tả hoạt động và các nhiệm vụ cần thực hiện…" }
};
function renderAI(root) {
  root.innerHTML = `${heading("Trợ lý AI", "Tiết kiệm thời gian cho công việc truyền thông và điều phối.")}
  <section class="ai-intro"><p class="eyebrow">AI CLUB ASSISTANT</p><h2>Ý tưởng tốt hơn, nhanh hơn.</h2><p>AI sẽ dựa trên thông tin bạn cung cấp để soạn thảo — hãy kiểm tra kết quả trước khi sử dụng.</p></section>
  <div class="ai-tabs">${Object.entries(aiDefinitions).map(([key, item]) => `<button class="ai-tab ${key === state.aiAction ? "active" : ""}" data-ai-tab="${key}">${item.label}</button>`).join("")}</div>
  <form class="ai-form" id="ai-form"><label id="ai-label">${aiDefinitions[state.aiAction].label}</label><textarea name="input" required placeholder="${aiDefinitions[state.aiAction].placeholder}"></textarea>${state.aiAction === "summary" ? '<label style="margin-top:14px">Phản hồi thành viên (không bắt buộc)</label><textarea name="feedback" placeholder="Nhập phản hồi sau hoạt động…"></textarea>' : ""}<button class="button primary">✦ Tạo nội dung</button><div id="ai-result"></div></form>`;
  document.querySelectorAll("[data-ai-tab]").forEach(button => button.addEventListener("click", () => { state.aiAction = button.dataset.aiTab; renderAI(root); }));
  document.querySelector("#ai-form").addEventListener("submit", async event => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const input = formData.get("input");
    const button = event.currentTarget.querySelector("button");
    button.disabled = true; button.textContent = "Đang tạo…";
    try {
      const body = state.aiAction === "announcement" ? { activity: input } : state.aiAction === "summary" ? { notes: input, feedback: formData.get("feedback") || "" } : { activity: input };
      const result = await api(`/ai/${state.aiAction}`, { method: "POST", body: JSON.stringify(body) });
      document.querySelector("#ai-result").innerHTML = `<div class="ai-result-box"><b>Kết quả gợi ý · Hãy kiểm tra trước khi sử dụng</b><div class="ai-result">${escapeHtml(result.result)}</div></div>`;
    } catch (error) { notify(error.message, true); }
    finally { button.disabled = false; button.innerHTML = "✦ Tạo nội dung"; }
  });
}
function bindForm(selector, path, method) {
  const form = document.querySelector(selector);
  if (!form) return;
  form.addEventListener("submit", async event => {
    event.preventDefault();
    try { const result = await api(path, { method, body: JSON.stringify(formValues(form)) }); notify(result.message || "Đã lưu thành công."); render(); }
    catch (error) { notify(error.message, true); }
  });
}
bindAuth();
document.querySelector("#logout-button").addEventListener("click", async () => {
  try { await api("/logout", { method: "POST" }); setLoggedOut(); }
  catch (error) { notify(error.message, true); }
});
document.querySelector("#home-brand").addEventListener("click", event => {
  event.preventDefault();
  if (!state.user.email_verified) {
    notify("Hãy xác minh email trong Hồ sơ của tôi trước.", true);
    state.page = "profile";
  } else {
    state.page = "dashboard";
  }
  render();
});
document.querySelectorAll(".profile-avatar").forEach(button => button.addEventListener("click", () => {
  state.page = "profile";
  render();
}));
document.querySelector("#navigation").addEventListener("click", event => {
  const button = event.target.closest("[data-page]");
  if (button) {
    if (!state.user.email_verified && button.dataset.page !== "profile") {
      notify("Hãy xác minh email trong Hồ sơ của tôi trước.", true);
      state.page = "profile";
      render();
      return;
    }
    state.page = button.dataset.page;
    render();
  }
});
document.querySelector("#content").addEventListener("click", event => {
  const button = event.target.closest("[data-goto]");
  if (button) { state.page = button.dataset.goto; render(); }
  if (event.target.closest("[data-scroll-form]")) document.querySelector(".form-card")?.scrollIntoView({ behavior: "smooth", block: "center" });
});
renderAuth();
api("/me").then(setLoggedIn).catch(setLoggedOut);
