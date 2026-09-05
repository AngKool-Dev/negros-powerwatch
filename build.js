const fs = require('fs');
const path = require('path');

const publicDir = 'public';
fs.mkdirSync(publicDir, { recursive: true });

['templates', 'static'].forEach(dir => {
  const items = fs.readdirSync(dir);
  items.forEach(item => {
    const src = path.join(dir, item);
    const dest = path.join(publicDir, item);
    copyRecursive(src, dest);
  });
});

function copyRecursive(src, dest) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    const items = fs.readdirSync(src);
    items.forEach(item => {
      copyRecursive(path.join(src, item), path.join(dest, item));
    });
  } else {
    fs.copyFileSync(src, dest);
  }
}

console.log('Build complete: frontend files copied to public/');
