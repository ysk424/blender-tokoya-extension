# Tokoya

Tokoya（床屋、英語では *barber*）は、Blender 5.1用のヘアースタイリング・アニメーション拡張です。グレースケールの頭皮マスクから毛を植え、Taichi XPBDで自然に垂らし、メッシュで切りそろえ、Bodyアニメーションに沿った動きを録画できます。

## 主な機能

- 白＝0 cm、黒＝最大長のUVペイントマスク
- 4,000本を既定値とする面積一様な植毛
- 根元が密で毛先ほど疎い、9点・8関節のストランド
- CUDA（既定）、Vulkan、CPUバックエンド
- 小数フレーム補間を使ったCUDAアニメーション録画と再生
- Blenderプロジェクトと同じ場所へ保存される圧縮キャッシュ
- ワールド座標BVH、点の連続衝突判定、セグメント衝突拘束
- `Mesh Shrink`による平面・球などを使ったカット
- `Urchin Reset`による直毛状態への復帰

セルフコリジョンは実装していません。

## 必要環境

- Blender 5.1以降
- Windows x64
- Pythonパッケージ `taichi`
- CUDA利用時は対応するNVIDIA GPUとドライバー

TaichiはBlenderが使用するPython 3.13環境から参照できるユーザーsite-packagesへインストールしてください。

## インストール

1. [Releases](../../releases)から最新の`tokoya-*.zip`をダウンロードします。
2. Blenderの`Edit > Preferences > Extensions`を開きます。
3. メニューから`Install from Disk`を選び、ZIPを指定します。
4. 3D ViewのNパネルに`Tokoya`タブが表示されます。

## 基本操作

1. 空のHair Curvesオブジェクトを作り、対象BodyへSurface設定します。
2. `Body`へアニメーション追従対象兼コライダーのMeshを設定します。
3. `Create Head Mask`で白いペイント用メッシュを作ります。
4. Texture Paintで毛を生やす範囲を黒または灰色で塗ります。
5. `Plant Hair`で植毛します。
6. `Simulate`で自然に垂らします。
7. 必要に応じてCutter Meshを指定し、`Mesh Shrink`で切りそろえます。

## アニメーション録画

1. タイムラインを録画開始フレームへ移動します。
2. `Frame Interpolation`を設定します。既定値は2です。
3. `REC`を押し、タイムラインを順方向へ再生します。
4. 計算はリアルタイムとは限りません。各フレームの計算完了後に次へ進みます。
5. `REC`をもう一度押すと録画を終了し、キャッシュ再生へ移行します。

逆再生またはフレームジャンプを行うと録画は中止され、再生モードへ移行します。破綻した場合は少し前の録画済みフレームへ戻り、`Frame Interpolation`を増やして再録画できます。再録画したフレーム以降の古いキャッシュは上書きされます。

REC中はフレームを飛ばさないよう、Playback Syncを一時的に`Play Every Frame`
へ変更します。録画終了時には元の設定へ戻します。

録画中に毛が動いて見えない場合は、まずTokoyaの`REC ●`が赤く表示され続けて
いるか確認してください。赤表示が消えた場合は、逆再生またはフレームジャンプ
として録画が中止されています。

時間刻みにはBlenderのFPSとFPS Baseを使用します。

```text
1フレームの秒数 = FPS Base / FPS
補間1回の秒数 = 1フレームの秒数 / Frame Interpolation
```

録画はRAMに保持され、`.blend`保存時に同じディレクトリへ
`<project>.blend.tokoya-cache.npz`として圧縮保存されます。このファイルを
`.blend`と一緒に保持すると、Blender再起動後も再生できます。

`Plant Hair`、`Hair Remove`、`Simulate`、`Mesh Shrink`、`Urchin Reset`で
髪形を変更すると、古い録画キャッシュは無効化されます。

長さを変更する場合は`Hair Remove`で毛だけを削除し、`Max Length`を変更して再植毛します。

## マスクの意味

```text
毛の長さ = (255 - 画素値) / 255 × Max Length
```

- 白（255）：0 cm
- 灰色：約半分の長さ
- 黒（0）：最大長

## 衝突処理

Bodyの評価済み形状からワールド座標BVHを構築します。各サブステップで点の移動経路と各ストランド区間を検査し、Body表面から0.5 mm外側へ拘束します。衝突補正量は速度へ変換せず、内向き法線速度だけを除去します。

Head MaskはBody表面から1 mm外側に生成されます。

## ライセンス

[MIT License](LICENSE)
