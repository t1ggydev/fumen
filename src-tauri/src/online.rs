//! Fumen's online features and downloads: searching and downloading maps on the mirrors, logging
//! in with osu!, the cloud, comparing with other players. They come with terms the first start
//! shows (fumen.dertesti.dev/terms): with them accepted, they're on; "only local" keeps them off,
//! and while they're off nothing here goes online (`ensure`). Settings › About can change it.
//!
//! With them on, every start runs the block check (`check`): the install's random id (ping.rs),
//! this computer's codes, the osu! login when there is one, and Fumen's version (a release build's
//! check also counts the start). The codes are SHA-256 hashes of Fumen's own key and ids the
//! system and the mainboard give themselves (Windows' MachineGuid and the SMBIOS UUID and serial
//! numbers; macOS' hardware UUID; Linux' machine-id): the ids never leave the computer, and the
//! codes can't be matched with what other apps send. Placeholder ids boards ship with are left
//! out. A block from the site is noted in `block.json`, so it holds offline (a full one also with
//! the online features off) until a check finds it lifted; any block closes `ensure`. Turning the
//! features off asks the site to take this computer's codes off its players list
//! (`forget_machine`; a block keeps them).
//!
//! What the site keeps of this: site/server.mjs (/api/check), and the privacy page.

use std::path::Path;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};

static ON: AtomicBool = AtomicBool::new(false);
/// The block the last check (or the note on disk) found, for `ensure`.
static BLOCK: Mutex<Option<Block>> = Mutex::new(None);

/// What the site said about this Fumen, for `ensure` (None: not blocked).
pub fn set_block(block: Option<Block>) {
    *BLOCK.lock().unwrap_or_else(|e| e.into_inner()) = block;
}

/// Switches the online features on or off for this run (Settings keeps the choice).
pub fn set(on: bool) {
    ON.store(on, Ordering::SeqCst);
}

pub fn is_on() -> bool {
    // the tests talk to their own local servers; a developer's own osu! app runs online without the site
    cfg!(test) || ON.load(Ordering::SeqCst) || crate::osu_auth::dev_app_configured()
}

/// Ok while the online features are on and not blocked; else what to tell the player.
pub fn ensure() -> Result<()> {
    // a developer's own osu! app goes straight to osu! and the mirrors, not the site — no block check
    if crate::osu_auth::dev_app_configured() {
        return Ok(());
    }
    if !is_on() {
        return Err(Error::known("online-off", "This needs Fumen's online features, and they're off. You can turn them on in Settings › About."));
    }
    // the tests talk to their own local servers, and set no block
    if cfg!(test) {
        return Ok(());
    }
    match BLOCK.lock().unwrap_or_else(|e| e.into_inner()).as_ref() {
        Some(b) => Err(Error::known("blocked", b.message.clone())),
        None => Ok(()),
    }
}

/// A block from fumen.dertesti.dev: "full" (Fumen shows only this) or "online" (nothing that
/// goes online: no login, no cloud, no mirrors). `message` is the site's, with the reason and where to turn.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Block {
    pub scope: String,
    pub message: String,
}

/// The build key of Fumen's own builds (build.rs); None in one built by anyone else.
const BUILD_KEY: Option<&str> = option_env!("FUMEN_BUILD_KEY");

/// Whether this is one of Fumen's own builds (one that can use fumen.dertesti.dev).
pub fn is_official() -> bool {
    BUILD_KEY.is_some()
}

/// HMAC-SHA256 (RFC 2104).
fn hmac_sha256(key: &[u8], message: &[u8]) -> [u8; 32] {
    use sha2::{Digest, Sha256};
    let mut block = [0u8; 64];
    if key.len() > 64 {
        block[..32].copy_from_slice(&Sha256::digest(key));
    } else {
        block[..key.len()].copy_from_slice(key);
    }
    let mut inner = Sha256::new();
    inner.update(block.map(|b| b ^ 0x36));
    inner.update(message);
    let mut outer = Sha256::new();
    outer.update(block.map(|b| b ^ 0x5c));
    outer.update(inner.finalize());
    outer.finalize().into()
}

/// The X-Fumen-Build header for a request: "<unix seconds>.<HMAC of seconds, method and path>",
/// which the site takes as a sign it comes from one of Fumen's own builds.
fn build_proof(key: &str, at: u64, method: &str, path: &str) -> String {
    let mac = hmac_sha256(key.as_bytes(), format!("{at}\n{method}\n{path}").as_bytes());
    format!("{at}.{}", mac.iter().map(|b| format!("{b:02x}")).collect::<String>())
}

/// A request to fumen.dertesti.dev, signed when this is one of Fumen's own builds. `path` is the
/// URL's path ("/api/check").
pub fn signed<B>(req: ureq::RequestBuilder<B>, method: &str, path: &str) -> ureq::RequestBuilder<B> {
    let Some(key) = BUILD_KEY else { return req };
    let at = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    req.header("X-Fumen-Build", &build_proof(key, at, method, path))
}

/// Where a full block is noted.
const NOTE: &str = "block.json";

/// The block noted on this computer, if there is one (full or online).
pub fn noted(data_dir: &Path) -> Option<Block> {
    let b: Block = serde_json::from_slice(&std::fs::read(data_dir.join(NOTE)).ok()?).ok()?;
    matches!(b.scope.as_str(), "full" | "online").then_some(b)
}

fn note(data_dir: &Path, block: Option<&Block>) {
    let file = data_dir.join(NOTE);
    match block {
        Some(b) => {
            if let Ok(bytes) = serde_json::to_vec(b) {
                let _ = std::fs::create_dir_all(data_dir);
                let _ = std::fs::write(file, bytes);
            }
        }
        None => {
            let _ = std::fs::remove_file(file);
        }
    }
}

/// The code for a computer with this system id.
fn code_of(id: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(b"fumen-machine-v1\0");
    h.update(id.trim().to_ascii_lowercase().as_bytes());
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

/// This computer's codes: the system's id first, then the mainboard's (at most four, without
/// placeholders).
pub fn machine_codes() -> Vec<String> {
    let mut codes: Vec<String> = machine_id().filter(|id| real_id(id)).map(|id| code_of(&id)).into_iter().collect();
    for (kind, value) in hardware_ids() {
        if real_id(&value) {
            let code = code_of(&format!("{kind}:{value}"));
            if !codes.contains(&code) {
                codes.push(code);
            }
        }
    }
    codes.truncate(4);
    codes
}

/// Whether an id from the system or the mainboard names this computer, not a placeholder many
/// boards ship with ("To be filled by O.E.M.", "Default string", 00000000…, 03000200-0400-…).
fn real_id(id: &str) -> bool {
    let compact: String = id.chars().filter(|c| c.is_ascii_alphanumeric()).map(|c| c.to_ascii_lowercase()).collect();
    let Some(first) = compact.chars().next() else { return false };
    if compact.len() < 5 || compact.chars().all(|c| c == first) {
        return false;
    }
    const WITHIN: [&str; 12] = [
        "tobefilled",
        "defaultstring",
        "systemserial",
        "serialnumber",
        "notapplicable",
        "notspecified",
        "notavailable",
        "chassisserial",
        "baseboardserial",
        "03000200040005000006000700080009",
        "0123456789",
        "123456789",
    ];
    const WHOLE: [&str; 6] = ["default", "unknown", "invalid", "nodata", "nonenone", "xxxxx"];
    !WITHIN.iter().any(|p| compact.contains(p)) && !WHOLE.contains(&compact.as_str())
}

/// The mainboard's ids from an SMBIOS structure table: the system UUID and serial number (type 1)
/// and the board's serial number (type 2), as (kind, value), placeholders and all.
fn smbios_ids(table: &[u8]) -> Vec<(&'static str, String)> {
    let mut out = Vec::new();
    let mut i = 0;
    while i + 4 <= table.len() {
        let (kind, len) = (table[i], table[i + 1] as usize);
        if len < 4 || i + len > table.len() {
            break;
        }
        let formatted = &table[i..i + len];
        // the strings after the formatted part, each ending in NUL, the set in another NUL
        let mut j = i + len;
        let mut strings: Vec<&[u8]> = Vec::new();
        if table.get(j) == Some(&0) {
            j += 2;
        } else {
            while let Some(p) = table.get(j..).and_then(|t| t.iter().position(|&b| b == 0)) {
                if p == 0 {
                    j += 1;
                    break;
                }
                strings.push(&table[j..j + p]);
                j += p + 1;
            }
        }
        let string = |at: usize| -> Option<String> {
            let n = (*formatted.get(at)? as usize).checked_sub(1)?;
            Some(String::from_utf8_lossy(strings.get(n)?).trim().to_string())
        };
        match kind {
            1 => {
                if let Some(uuid) = formatted.get(8..24) {
                    out.push(("board-uuid", uuid.iter().map(|b| format!("{b:02x}")).collect()));
                }
                out.extend(string(7).map(|s| ("system-serial", s)));
            }
            2 => out.extend(string(7).map(|s| ("board-serial", s))),
            127 => break,
            _ => {}
        }
        i = j;
    }
    out
}

/// The mainboard's ids (Windows: the SMBIOS table, readable without admin rights).
#[cfg(windows)]
fn hardware_ids() -> Vec<(&'static str, String)> {
    use windows_sys::Win32::System::SystemInformation::GetSystemFirmwareTable;
    let rsmb = u32::from_be_bytes(*b"RSMB");
    // SAFETY: a null buffer of size 0 only asks for the size
    let size = unsafe { GetSystemFirmwareTable(rsmb, 0, std::ptr::null_mut(), 0) };
    if size == 0 || size > 1 << 20 {
        return Vec::new();
    }
    let mut buf = vec![0u8; size as usize];
    // SAFETY: the buffer is exactly as long as said
    let got = unsafe { GetSystemFirmwareTable(rsmb, 0, buf.as_mut_ptr(), size) };
    if got == 0 || got > size || buf.len() < 8 {
        return Vec::new();
    }
    // RawSMBIOSData: four bytes of versions, the table's length, then the table
    let len = u32::from_le_bytes([buf[4], buf[5], buf[6], buf[7]]) as usize;
    smbios_ids(&buf[8..(8 + len).min(got as usize)])
}

#[cfg(not(windows))]
fn hardware_ids() -> Vec<(&'static str, String)> {
    Vec::new()
}

#[cfg(windows)]
fn machine_id() -> Option<String> {
    use windows_sys::Win32::System::Registry::{RegGetValueW, HKEY_LOCAL_MACHINE, RRF_RT_REG_SZ, RRF_SUBKEY_WOW6464KEY};
    let key: Vec<u16> = "SOFTWARE\\Microsoft\\Cryptography\0".encode_utf16().collect();
    let name: Vec<u16> = "MachineGuid\0".encode_utf16().collect();
    let mut buf = [0u16; 128];
    let mut size = std::mem::size_of_val(&buf) as u32;
    // SAFETY: the names end in NUL, the buffer and its size in bytes go together
    let r = unsafe {
        RegGetValueW(HKEY_LOCAL_MACHINE, key.as_ptr(), name.as_ptr(), RRF_RT_REG_SZ | RRF_SUBKEY_WOW6464KEY, std::ptr::null_mut(), buf.as_mut_ptr().cast(), &mut size)
    };
    if r != 0 {
        return None;
    }
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    let id = String::from_utf16_lossy(&buf[..end]).trim().to_string();
    (!id.is_empty()).then_some(id)
}

#[cfg(target_os = "macos")]
fn machine_id() -> Option<String> {
    let out = std::process::Command::new("/usr/sbin/ioreg").args(["-rd1", "-c", "IOPlatformExpertDevice"]).output().ok()?;
    let text = String::from_utf8_lossy(&out.stdout);
    // "IOPlatformUUID" = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
    let line = text.lines().find(|l| l.contains("\"IOPlatformUUID\""))?;
    let id = line.rsplit('"').nth(1)?.trim();
    (!id.is_empty()).then(|| id.to_string())
}

#[cfg(target_os = "linux")]
fn machine_id() -> Option<String> {
    ["/etc/machine-id", "/var/lib/dbus/machine-id"]
        .iter()
        .find_map(|p| std::fs::read_to_string(p).ok().map(|s| s.trim().to_string()).filter(|s| !s.is_empty()))
}

#[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
fn machine_id() -> Option<String> {
    None
}

fn agent() -> ureq::Agent {
    ureq::Agent::config_builder()
        .user_agent(crate::downloads::USER_AGENT)
        .timeout_global(Some(Duration::from_secs(15)))
        .https_only(cfg!(not(test)))
        .http_status_as_error(false)
        .build()
        .into()
}

/// Asks `site` whether this Fumen is blocked: with the install's random id and version, this
/// computer's codes when `machine` (only with the online features on, which also counts a release
/// build's start), and the osu! login while it's current. A block is noted on disk and closes
/// `ensure`; none lifts both.
pub fn check(data_dir: &Path, site: &str, machine: bool) -> Result<Option<Block>> {
    let install = crate::ping::install_id(data_dir).ok_or_else(|| Error::known("check-failed", "Fumen couldn't make its random id."))?;
    let mut body = serde_json::json!({ "install": install, "version": env!("CARGO_PKG_VERSION"), "count": machine && !cfg!(debug_assertions) });
    if machine {
        let codes = machine_codes();
        if !codes.is_empty() {
            body["machines"] = codes.into();
        }
    }
    let agent = agent();
    let mut req = signed(agent.post(&format!("{site}/api/check")), "POST", "/api/check").header("Content-Type", "application/json");
    if let Some(token) = crate::osu_auth::current_token(data_dir) {
        req = req.header("Authorization", &format!("Bearer {token}"));
    }
    let mut res = req.send(body.to_string()).map_err(|e| Error::known("check-failed", format!("fumen.dertesti.dev didn't answer ({e})")))?;
    if res.status() != 200 {
        let status = res.status().as_u16();
        let said: serde_json::Value = res.body_mut().read_to_string().ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default();
        // a Fumen someone else built: the site says so
        if said["error"] == "unofficial" {
            return Err(Error::known("unofficial", said["message"].as_str().unwrap_or("This Fumen can't use fumen.dertesti.dev.").to_string()));
        }
        return Err(Error::known("check-failed", format!("fumen.dertesti.dev answered {status}")));
    }
    let text = res.body_mut().read_to_string().unwrap_or_default();
    let answer: serde_json::Value = serde_json::from_str(&text).unwrap_or_default();
    let block = answer.get("blocked").and_then(|b| serde_json::from_value::<Block>(b.clone()).ok());
    note(data_dir, block.as_ref());
    set_block(block.clone());
    Ok(block)
}

/// Asks `site` to take this computer's codes off its players list (the online features were
/// turned off). In the background; a failure is silent.
pub fn forget_machine(site: String) {
    std::thread::spawn(move || {
        let codes = machine_codes();
        if codes.is_empty() {
            return;
        }
        let body = serde_json::json!({ "machines": codes });
        let _ = signed(agent().post(&format!("{site}/api/forget-machine")), "POST", "/api/forget-machine").header("Content-Type", "application/json").send(body.to_string());
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_computer_code_hides_the_id() {
        let a = code_of("4c4c4544-0042-3510-8051-b4c04f384d32");
        assert_eq!(a.len(), 64);
        assert!(a.bytes().all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()));
        // the same computer, however the id is written; another computer, another code
        assert_eq!(a, code_of(" 4C4C4544-0042-3510-8051-B4C04F384D32\n"));
        assert_ne!(a, code_of("4c4c4544-0042-3510-8051-b4c04f384d33"));
        assert!(!a.contains("4c4c4544"));
        // this computer has some (Windows always gives one), the same each time
        let codes = machine_codes();
        #[cfg(windows)]
        assert!(!codes.is_empty());
        assert!(codes.len() <= 4 && codes.iter().all(|c| c.len() == 64));
        assert_eq!(machine_codes(), codes);
        println!("this computer: {} codes", codes.len());
    }

    #[test]
    fn signs_like_the_site_checks() {
        // RFC 4231, test case 2
        let mac = hmac_sha256(b"Jefe", b"what do ya want for nothing?");
        assert_eq!(mac.iter().map(|b| format!("{b:02x}")).collect::<String>(), "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843");
        // the same proof site/server.test.mjs expects
        let key = "0123456789abcdef".repeat(4);
        assert_eq!(build_proof(&key, 1_800_000_000, "POST", "/api/check"), "1800000000.792a70eb0117e97059080835fecd749c31a35866b80fae1a54a33fc5a54b4a62");
    }

    #[test]
    fn placeholders_name_no_computer() {
        for fake in ["To be filled by O.E.M.", "Default string", "System Serial Number", "00000000-0000-0000-0000-000000000000", "ffffffffffffffffffffffffffffffff", "03000200040005000006000700080009", "None", "0", "", "  ", "123456789", "Not Applicable", "xxxxx"] {
            assert!(!real_id(fake), "{fake:?} passed as a real id");
        }
        for real in ["4c4c4544-0042-3510-8051-b4c04f384d32", "PF3ABC12", "MS-7C02-SN-8473920", "2f7e9a40c1d5e8b3a6f4d2c1b0e9a8f7"] {
            assert!(real_id(real), "{real:?} was taken for a placeholder");
        }
    }

    #[test]
    fn reads_the_mainboard_from_smbios() {
        let mut t = Vec::new();
        // type 0 (firmware), no strings
        t.extend([0u8, 4, 0, 0, 0, 0]);
        // type 1: header, maker/product/version strings (1-3), serial (4), the UUID at 8
        let mut one = vec![1u8, 27, 1, 0, 1, 2, 3, 4];
        one.extend((0x10..0x20).collect::<Vec<u8>>());
        one.extend([6, 0, 0]);
        t.extend(&one);
        t.extend(b"Maker\0Box\0v1\0SERIAL-1234\0\0");
        // type 2: board, serial at 7 (string 2)
        t.extend([2u8, 8, 2, 0, 1, 0, 0, 2]);
        t.extend(b"Board Maker\0Default string\0\0");
        t.extend([127u8, 4, 3, 0, 0, 0]);
        let ids = smbios_ids(&t);
        assert_eq!(
            ids,
            vec![
                ("board-uuid", "101112131415161718191a1b1c1d1e1f".to_string()),
                ("system-serial", "SERIAL-1234".to_string()),
                ("board-serial", "Default string".to_string()),
            ]
        );
        assert_eq!(ids.iter().filter(|(_, v)| real_id(v)).count(), 2);
        // a cut-off table stops without a panic
        assert!(smbios_ids(&t[..30]).len() <= 2);
    }

    #[test]
    fn a_full_block_is_noted_until_lifted() {
        let dir = std::env::temp_dir().join(format!("fumen-block-{}", std::process::id()));
        let full = Block { scope: "full".into(), message: "Fumen is blocked on this computer. Reason: cheating".into() };
        assert_eq!(noted(&dir), None);
        note(&dir, Some(&full));
        assert_eq!(noted(&dir), Some(full));
        // an online block is noted too (the start shows it, and it holds offline)
        let online = Block { scope: "online".into(), message: "x".into() };
        note(&dir, Some(&online));
        assert_eq!(noted(&dir), Some(online));
        // anything else the file might hold isn't a block
        std::fs::write(dir.join(NOTE), r#"{"scope":"other","message":"x"}"#).unwrap();
        assert_eq!(noted(&dir), None);
        note(&dir, None);
        assert_eq!(noted(&dir), None);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
