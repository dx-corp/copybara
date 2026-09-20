use std::{env, fs, path::Path};

fn main() {
    let args: Vec<_> = env::args().collect();
    let result = (|| {
        if args.len() != 6 {
            return Err("usage: copybara-prepared-tree DESTINATION PREPARED BASE_SHA MANAGED_NUL ORIGIN_NUL".into());
        }
        copybara_prepared_tree::build_tree(
            Path::new(&args[1]),
            Path::new(&args[2]),
            &args[3],
            &fs::read(&args[4])?,
            &fs::read(&args[5])?,
        )
    })();
    match result {
        Ok(tree) => println!("{tree}"),
        Err(error) => {
            eprintln!("prepared-tree: {error}");
            std::process::exit(1);
        }
    }
}
