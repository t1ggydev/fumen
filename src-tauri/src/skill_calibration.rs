//! Offline NoMod library export; reads the library without migrations and writes a separate cache.
use std::collections::{HashSet, VecDeque};
use std::io::{BufWriter, Write};
use std::path::Path;
use std::sync::{Arc, Mutex, atomic::{AtomicUsize, Ordering}};
use md5::Digest;
use rusqlite::{Connection, OpenFlags};

pub fn export(database: &Path, output: &Path) -> Result<(), Box<dyn std::error::Error>> {
    std::fs::create_dir_all(output)?;
    let db = Connection::open_with_flags(database, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    db.busy_timeout(std::time::Duration::from_secs(10))?;
    let files = crate::paths::Files {
        lazer: crate::db::get_meta(&db, "lazer.storage")?.map(Into::into),
        stable: Arc::new(crate::stable::load_files(&db)?),
    };
    let maps = db.prepare("SELECT m.id, COALESCE(m.hash,''), s.artist, s.title, m.version FROM maps m JOIN sets s ON s.id=m.set_id WHERE m.ruleset_id=0 ORDER BY m.id")?
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?, r.get::<_, String>(4)?)))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    drop(db);
    let total = maps.len();
    let cache = Connection::open(output.join("patterns.sqlite"))?;
    cache.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
        CREATE TABLE IF NOT EXISTS osu_skill_charts(hash TEXT,mods TEXT,rate INTEGER,version INTEGER,data BLOB,PRIMARY KEY(hash,mods,rate,version));")?;
    let cache = Mutex::new(cache);
    let queue = Mutex::new(VecDeque::from(maps));
    let seen = Mutex::new(HashSet::new());
    let results = Mutex::new(Vec::new());
    let done = AtomicUsize::new(0);
    let duplicates = AtomicUsize::new(0);
    let unreadable = AtomicUsize::new(0);
    let failed = AtomicUsize::new(0);
    eprintln!("Export: {total} standard maps, NoMod 1.0x, 4 workers");
    std::thread::scope(|scope| {
        for _ in 0..4 {
            scope.spawn(|| loop {
                let Some((id, key, artist, title, version)) = queue.lock().unwrap().pop_front() else { break };
                if let Some(bytes) = files.read(&key) {
                    let hash = format!("{:x}", md5::Md5::digest(&bytes));
                    if !seen.lock().unwrap().insert(hash.clone()) { duplicates.fetch_add(1, Ordering::Relaxed); }
                    else {
                        let p = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| crate::osu_skills::calibration_sample(&bytes, &cache, &hash)));
                        if let Ok(Some(pattern)) = p {
                            let holdout = u64::from_str_radix(&hash[..16], 16).unwrap() % 5 == 0;
                            results.lock().unwrap().push(serde_json::json!({ "id": id, "hash": hash, "artist": artist,
                                "title": title, "version": version, "holdout": holdout, "pattern": pattern }));
                        } else { failed.fetch_add(1, Ordering::Relaxed); }
                    }
                } else { unreadable.fetch_add(1, Ordering::Relaxed); }
                let n = done.fetch_add(1, Ordering::Relaxed) + 1;
                if n % 1000 == 0 || n == total { eprintln!("{n}/{total}"); }
            });
        }
    });
    let mut results = results.into_inner().unwrap();
    results.sort_by(|a, b| a["hash"].as_str().cmp(&b["hash"].as_str()));
    let mut writer = BufWriter::new(std::fs::File::create(output.join("maps.jsonl"))?);
    for row in &results { serde_json::to_writer(&mut writer, row)?; writeln!(writer)?; }
    writer.flush()?;
    let metadata = serde_json::json!({ "model": crate::osu_skills::calibration_model(),
        "total": total, "analyzed": results.len(), "duplicates": duplicates.load(Ordering::Relaxed),
        "unreadable": unreadable.load(Ordering::Relaxed), "failed": failed.load(Ordering::Relaxed),
        "skills": crate::osu_skills::SKILLS.iter().map(|s| (s.0,s.1)).collect::<Vec<_>>() });
    std::fs::write(output.join("export.json"), serde_json::to_vec_pretty(&metadata)?)?;
    eprintln!("Export complete: {} unique maps", results.len());
    Ok(())
}

/// Repeatable profile audit. The caller supplies a disposable database snapshot.
pub fn audit(database: &Path, data: &Path, charts: &Path, output: &Path, names: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    use std::sync::atomic::AtomicBool;
    if database.canonicalize()? == data.join("library.db").canonicalize()? {
        return Err("Use a disposable SQLite backup, not Fumen's original library.db".into());
    }
    std::fs::create_dir_all(output)?;
    let conn = Connection::open(database)?;
    conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")?;
    let files = crate::paths::Files {
        lazer: crate::db::get_meta(&conn, "lazer.storage")?.map(Into::into),
        stable: Arc::new(crate::stable::load_files(&conn)?),
    };
    let account = crate::osu_auth::account(data);
    let history: serde_json::Value = serde_json::from_slice(&crate::osu_scores::history_json(&conn, account.as_ref(), None)?)?;
    let plays: Vec<crate::osu_skills::StdPlay> = history["plays"].as_array().unwrap().iter()
        .filter(|p| p["mode"] == 0 && p["map"].is_string() && p["failed"] != true)
        .map(|p| serde_json::from_value(p.clone())).collect::<Result<_,_>>()?;
    let hashes: std::collections::HashMap<String,String> = conn.prepare("SELECT id,hash FROM maps WHERE hash IS NOT NULL")?
        .query_map([], |r| Ok((r.get(0)?,r.get(1)?)))?.collect::<rusqlite::Result<_>>()?;
    let db = Mutex::new(conn);
    eprintln!("Own profile: {} passes", plays.len());
    let result = crate::osu_skills::skills(|h| files.read(h), &db, &hashes, &plays)?;
    let metadata: Vec<serde_json::Value> = db.lock().unwrap().prepare("SELECT m.id,s.artist,s.title,m.version FROM maps m JOIN sets s ON s.id=m.set_id")?
        .query_map([], |r| Ok(serde_json::json!({"map":r.get::<_,String>(0)?,"artist":r.get::<_,String>(1)?,"title":r.get::<_,String>(2)?,"version":r.get::<_,String>(3)?})))?
        .collect::<rusqlite::Result<_>>()?;
    let own = serde_json::json!({"model":crate::osu_skills::calibration_model(),"player": history["player"], "skills": result.skills,"overall": result.overall,"summary":result.summary,"plays":history["plays"].as_array().unwrap().iter().filter(|p|p["mode"]==0 && p["map"].is_string() && p["failed"]!=true).collect::<Vec<_>>(),"maps":metadata});
    std::fs::write(output.join("own.json"),serde_json::to_vec_pretty(&own)?)?;
    let ep = crate::osu_auth::Endpoints::default();
    crate::online::set(crate::settings::Settings::load(&data.join("settings.json")).online);
    crate::online::set_block(crate::online::noted(data));
    let cancel = AtomicBool::new(false);
    let inputs = output.parent().unwrap_or(output).join("profile-inputs");
    std::fs::create_dir_all(&inputs)?;
    for name in names {
        if !name.chars().all(|c| c.is_ascii_alphanumeric() || "_- ".contains(c)) {
            return Err("Invalid player name for audit filename".into());
        }
        let destination = output.join(format!("{name}.json"));
        let input = inputs.join(format!("{name}.json"));
        let fetched = if input.exists() {
            eprintln!("Reusing score input {}", input.display());
            serde_json::from_slice::<crate::player::Fetched>(&std::fs::read(&input)?)?
        } else {
            eprintln!("Fetching profile {name}");
            let fetched = crate::osu_auth::with_token(data, &ep, |token| crate::player::fetch(&ep,token,name,0,"osu",&cancel,|p|eprintln!("{name}: {:?}",p)))?;
            std::fs::write(&input, serde_json::to_vec(&fetched)?)?;
            fetched
        };
        let bytes = crate::player::build_std(&files,charts,&db,fetched,&cancel,|p|eprintln!("{name}: {:?}",p))?;
        let mut result: serde_json::Value = serde_json::from_slice(&bytes)?;
        result["model"] = crate::osu_skills::calibration_model().into();
        std::fs::write(destination,serde_json::to_vec_pretty(&result)?)?;
    }
    Ok(())
}
