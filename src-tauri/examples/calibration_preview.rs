fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 { return Err("Usage: calibration_preview LIBRARY_DB OUTPUT_DIRECTORY".into()) }
    fumen_lib::skill_calibration::export(std::path::Path::new(&args[0]), std::path::Path::new(&args[1]))
}
