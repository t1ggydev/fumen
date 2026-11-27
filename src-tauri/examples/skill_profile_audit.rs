fn main() -> Result<(), Box<dyn std::error::Error>> {
    let a:Vec<String> = std::env::args().skip(1).collect();
    if a.len()<4 { return Err("Usage: skill_profile_audit SNAPSHOT_DB APP_DATA CHART_CACHE OUTPUT [PLAYERS...]".into()) }
    fumen_lib::skill_calibration::audit(a[0].as_ref(),a[1].as_ref(),a[2].as_ref(),a[3].as_ref(),&a[4..])
}
