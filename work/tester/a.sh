#!/bin/bash

for seed in {0..100}; do
  # seedを4桁のゼロ埋め形式に変換（例: 0 -> 0000, 1 -> 0001）
  filename=$(printf "./../in/%04d.txt" $seed)
  # java Generator を実行し、出力をファイルにリダイレクト
  java Generator -seed $seed > $filename
done
