#! python
# coding:utf-8

import math
import copy

import importlib

import maya.cmds as cmds
import maya.mel as mel

import nnutil as nu

# TODO: カーブを比率で分割しても曲率の違いで 全体曲線:部分曲線 と 全体折れ線:部分直線 の比率が一致しない問題どうにかする (元の比率をキャッシュする？)
# TODO: ループ時の対応 (メッセージ出しつつ適当な所始点にしてしまいたい)
# TODO: コンポーネントIDが変化したときに元の形状に近いエッジ列を推定する機能

# TODO: U値スライダー

DEBUG = False

window_width = 300
header_width = 50
color_x = (1.0, 0.5, 0.5)
color_y = (0.5, 1.0, 0.5)
color_z = (0.5, 0.5, 1.0)
color_joint = (0.5, 1.0, 0.75)
color_select = (0.5, 0.75, 1.0)
bw_single = 24
bw_double = bw_single*2 + 2
bw_3 = bw_single*3 + 2


# アトリビュートにエッジ列を文字列で保存する際の区切り文字
component_separator = ','

# このツールで生成されるカーブノードの名称につけるプリフィックス
curve_prefix = "NNAEOC_Curve"

# エッジ列をカーブに保存する際のカスタムアトリビュート名
attr_name = "dst_edges"

def printd(description, message):
    if DEBUG:
        print(str(description) + ": " + str(message))

def addAttributes(curve, edges):
    """
    カーブオブジェクトにアトリビュート追加
    """

    edges_str = edges
    curve_str = curve
    attr_fullname = curve_str + "." + attr_name

    if not cmds.attributeQuery(attr_name, node=curve_str, exists=True):
        cmds.addAttr(curve_str, ln=attr_name, dt="string")

    cmds.setAttr(attr_fullname, edges_str, e=True, type="string")
    cmds.setAttr(attr_fullname, e=True, channelBox=True)

def changeAppearance(curve):
    """カーブの見た目を変更する"""
    line_width = 2
    color = [1.0, 0.3, 0.0]

    cmds.setAttr('%s.lineWidth' % curve, line_width)
    cmds.setAttr('%s.overrideEnabled' % curve, 1)
    cmds.setAttr('%s.overrideRGBColors' % curve, 1)
    cmds.setAttr('%s.overrideColorR' % curve, color[0])
    cmds.setAttr('%s.overrideColorG' % curve, color[1])
    cmds.setAttr('%s.overrideColorB' % curve, color[2])
    cmds.setAttr('%s.useOutlinerColor' % curve, True)
    cmds.setAttr('%s.outlinerColor' % curve, color[0],color[1],color[2])

def makeCurve(edges, n=4):
    """
    引数のエッジ列からカーブを生成してアトリビュート付与する
    連続しない複数エッジ列の場合はエラーを返す (エッジ列の分割は関数の外で行う)
    """

    # カーブ作成
    cmds.select(edges, replace=True)
    curve = cmds.polyToCurve(form=2, degree=3, conformToSmoothMeshPreview=1)[0]

    # リビルドしてヒストリ消す
    cmds.rebuildCurve(curve, ch=1, rpo=1, rt=0, end=1, kr=0, kcp=0, kep=1, kt=0, s=n, d=3, tol=0.01)
    cmds.DeleteHistory(curve)

    # 見た目の変更
    changeAppearance(curve)

    # 選択エッジ集合と構成頂点
    edge_set = edges
    vtx_set = cmds.filterExpand(
        cmds.polyListComponentConversion(edges, fe=True, tv=True), sm=31)

    end_vts = nu.get_end_vtx_e(edge_set)

    # 開いた状態の連続した一本のエッジ列以外は現状エラーで終了
    if not len(end_vts) == 2:
        raise(Exception)

    sorted_vts = nu.sortVtx(edge_set, vtx_set)

    # カーブの始点終点と頂点リストお始点終点が逆なら頂点リストを反転する
    if not nu.isStart(sorted_vts[0], curve):
        sorted_vts.reverse()

    addAttributes(curve, edges)

    return [curve, edges]


def alignEdgesOnCurve(edges, curve, keep_ratio_mode=True, n=4):
    """
    edges 編集するエッジ
    curve 整形に使用するカーブ
    keep_ratio_mode Trueなら元のエッジの長さの比率を維持する, False なら頂点をカーブ上に均等配置する
    """

    # 内部リビルド
    # 直線時に開始位置がずれるバグ対策も兼ね
    target_curve = cmds.duplicate(curve)
    k = 8
    cmds.rebuildCurve(target_curve, ch=1, rpo=1, rt=0, end=1, kr=0, kcp=0, kep=1, kt=0, s=n*k, d=3, tol=0.01)
    cmds.DeleteHistory(target_curve)

    # 選択エッジ集合と構成頂点
    edge_set = edges
    vtx_set = cmds.filterExpand(
        cmds.polyListComponentConversion(edges, fe=True, tv=True), sm=31)

    end_vts = nu.get_end_vtx_e(edge_set)

    # 閉じていない連続した一本のエッジ列以外は現状エラーで終了
    if not len(end_vts) == 2:
        raise(Exception)

    sorted_vts = nu.sortVtx(edge_set, vtx_set)

    # カーブの始点終点と頂点リストお始点終点が逆なら頂点リストを反転する
    if not nu.isStart(sorted_vts[0], target_curve):
        sorted_vts.reverse()

    # 各頂点の移動先の座標を計算
    new_positions = []

    if keep_ratio_mode:
        # 頂点列間の比率を維持してカーブに再配置
        for i in range(len(sorted_vts)):
            u = nu.vtxListPath(sorted_vts, i)/nu.vtxListPath(sorted_vts)
            new_positions.append(cmds.pointOnCurve(target_curve, pr=u, p=True))

    else:  # even space mode
        # 頂点列間の比率を無視してカーブに等間隔で配置
        for i in range(len(sorted_vts)):
            u = float(i)/(len(sorted_vts)-1)
            new_positions.append(cmds.pointOnCurve(target_curve, pr=u, p=True))

    # 実際のコンポーネント移動
    for i in range(len(sorted_vts)):
        cmds.xform(sorted_vts[i], ws=True, t=new_positions[i])

    cmds.delete(target_curve)

    return [target_curve, edges]

    # TODO: カーブ・エッジの同期モード欲しい
    """
      両方向コンストレイント
      頂点が変更されたらカーブを再生成
      カーブが変更されたら keep ratio mode で頂点を更新する
      カーブで形を変えて、頂点でエッジフローだけ直すのを平行してやる感じ
    """

def isValid(curve):
    """
    このツールで利用できる有効なカーブかどうかの判定
    """
    return cmds.attributeQuery(attr_name, node=curve, exists=True)

def isAvailable(curve):
    """
    processAll 時に fitToCurve を適用するなら Trueを返す
    現状はビジビリティで判定
    """
    return cmds.getAttr("%(curve)s.visibility"%locals())

def getAllCurves():
    """
    このツールで生成したカーブをすべて取得する
    """
    return cmds.ls(curve_prefix + "*")

class NN_ToolWindow(object):


    def __init__(self):
        self.window = 'NN_Curve'
        self.title = 'NN_Curve'
        self.size = (350, 95)


    def create(self):
        if cmds.window(self.window, exists=True):
            cmds.deleteUI(self.window, window=True)
        self.window = cmds.window(
            self.window,
            t=self.title,
            widthHeight=self.size
        )
        self.layout()
        cmds.showWindow()

        cmds.textField(self.tx_rebuild_resolution, e=True, tx=4)

    def layout(self):
        self.columnLayout = cmds.columnLayout()

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Make' ,width=header_width)
        self.bt_ = cmds.button(l='Make Curve', c=self.onMakeCurve)
        self.bt_ = cmds.button(l='Set Active', c=self.onSetActive)
        cmds.setParent("..")

        cmds.separator(width=window_width)

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Active Objects' )
        cmds.setParent("..")

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Edges' ,width=header_width)
        self.ed_edges = cmds.textField(tx='')
        self.bt_hoge = cmds.button(l='Set', c=self.onSetEdges)
        self.bt_hoge = cmds.button(l='Sel', c=self.onSelectEdges)
        cmds.setParent("..")

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Curve' ,width=header_width)
        self.ed_curve = cmds.textField(tx='')
        self.bt_hoge = cmds.button(l='Set', c=self.onSetCurve)
        self.bt_hoge = cmds.button(l='Sel', c=self.onSelectCurve)
        cmds.setParent("..")



        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.bt_ = cmds.button(l='Fit to Curve', c=self.onFitActive, width=bw_3)
        self.bt_ = cmds.button(l='Rebuild', c=self.onRebuildActive, width=bw_3)
        self.bt_ = cmds.button(l='Smooth', c=self.onSmoothActive, width=bw_3)
        cmds.setParent("..")

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.bt_ = cmds.button(l='Remake', c=self.onReMakeCurve, width=bw_3)
        self.bt_ = cmds.button(l='Reassign', c=self.onReAssignEdges, width=bw_3)
        cmds.setParent("..")

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.cb_keep_ratio_mode = cmds.checkBox(l='keep ratio', v=True, cc=self.onSetKeepRatio)
        self.bt_ = cmds.button(l='/2', c=self.onRebuildResolutionDiv2)
        self.tx_rebuild_resolution = cmds.textField(tx='', width=32)
        self.bt_ = cmds.button(l='x2', c=self.onRebuildResolutionMul2)
        cmds.setParent("..")

        cmds.separator(width=window_width)

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Fit' ,width=header_width)
        self.bt_ = cmds.button(l='Fit All', c=self.onFitAll, width=bw_3)
        self.bt_ = cmds.button(l='Selected', c=self.onFitSelection, width=bw_double)
        cmds.setParent("..")

        cmds.separator(width=window_width)

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Rebuild' ,width=header_width)
        self.bt_ = cmds.button(l='Rebuild All', c=self.onRebuildAll, width=bw_3)
        self.bt_ = cmds.button(l='Selected', c=self.onRebuildSelection, dgc=self.onRebuildOp, width=bw_double)
        self.bt_ = cmds.button(l='[Op]', c=self.onRebuildOp, width=bw_single)
        cmds.setParent("..")

        cmds.separator(width=window_width)

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Smooth' ,width=header_width)
        self.bt_ = cmds.button(l='Smooth All', c=self.onSmoothAll, width=bw_3)
        self.bt_ = cmds.button(l='Selected', c=self.onSmoothSelection, dgc=self.onSmoothOp, width=bw_double)
        self.bt_ = cmds.button(l='[Op]', c=self.onSmoothOp, width=bw_single)
        cmds.setParent("..")

        cmds.separator(width=window_width)

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Select' ,width=header_width)
        self.bt_ = cmds.button(l='Select All', c=self.onSelectAll, width=bw_3)
        self.bt_ = cmds.button(l='Visible [inv]', c=self.onSelectVisible, dgc=self.onSelectInvisible, width=bw_3)
        cmds.setParent("..")

        cmds.separator(width=window_width)

        self.rowLayout1 = cmds.rowLayout(numberOfColumns=10)
        self.label1 = cmds.text( label='Display' ,width=header_width)
        self.bt_ = cmds.button(l='Draw On Top [off]', c=self.onEnableDrawOnTop, dgc=self.onDisableDrawOnTop)
        cmds.setParent("..")

    def onSetKeepRatio(self, *args):
        pass

    def onMakeCurve(self, *args):
        """
        カーブ生成とアトリビュート設定
        """
        keep_ratio_mode = cmds.checkBox(self.cb_keep_ratio_mode, q=True, v=True)
        resolution = int(cmds.textField(self.tx_rebuild_resolution, q=True, tx=True))

        selections = cmds.ls(selection=True, flatten=True)

        polyline_list = nu.get_all_polylines(selections)

        for edges in polyline_list:
            # 選択エッジ列からカーブ生成
            ret = makeCurve(edges, n=resolution)
            curve = ret[0]
            edges = ret[1]

            # リネーム
            curve = cmds.rename(curve, curve_prefix, ignoreShape=True)

            # 生成されたカーブと選択エッジをエディットボックスに設定
            edges_str = component_separator.join(edges)
            cmds.textField(self.ed_edges, e=True, tx=edges_str)
            curve_str = curve
            cmds.textField(self.ed_curve, e=True, tx=curve_str)

            # カーブオブジェクトにアトリビュート追加
            edges_str = cmds.textField(self.ed_edges, q=True, tx=True)
            curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
            addAttributes(curve_str, edges_str)

    def onSetActive(self, *args):
        """
        選択オブジェクトとカーブからフィールドを入力
        メッシュとカーブが選択されている場合
            カーブは選択カーブをそのまま
            エッジ列はカーブの始点終点の最短パスエッジ列を設定
        カーブのみ選択されている場合は特殊アトリビュートが存在すればその値をセットする
            アトリビュート無しカーブのみの選択なら警告して何もしない
        """
        # TODO:オブジェクトとカーブ選択した場合の処理実装して

        selections = cmds.ls(selection=True)

        if len(selections) is 0:
            return

        if curve_prefix in selections[0]:
            curve_str = selections[0]
            attr_fullname = curve_str + "." + attr_name
            edges_str = cmds.getAttr(attr_fullname)
            cmds.textField(self.ed_curve, e=True, tx=curve_str)
            cmds.textField(self.ed_edges, e=True, tx=edges_str)


    def onSetEdges(self, *args):
        """
        選択エッジの取得
        """
        edges = cmds.ls(selection=True, flatten=True)
        edges_str = component_separator.join(edges)
        cmds.textField(self.ed_edges, e=True, tx=edges_str)

        # カーブオブジェクトにアトリビュート追加
        edges_str = cmds.textField(self.ed_edges, q=True, tx=True)
        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        if not curve_str is "":
            addAttributes(curve_str, edges_str)


    def onSelectEdges(self, *args):
        edges_str = cmds.textField(self.ed_edges, q=True, tx=True)
        edges = edges_str.split(component_separator)

        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        curve = curve_str

        cmds.select(edges)

    def onSetCurve(self, *args):
        """
        選択カーブの取得
        """
        curve = cmds.ls(selection=True, flatten=True)[0]
        cmds.textField(self.ed_curve, e=True, tx=curve)

        # カーブオブジェクトにアトリビュート追加
        edges_str = cmds.textField(self.ed_edges, q=True, tx=True)
        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        if not curve_str is "":
            addAttributes(curve_str, edges_str)

    def onSelectCurve(self, *args):
        edges_str = cmds.textField(self.ed_edges, q=True, tx=True)
        edges = edges_str.split(component_separator)

        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        curve = curve_str

        cmds.select(curve)


    def onFitActive(self, *args):
        edges_str = cmds.textField(self.ed_edges, q=True, tx=True)
        edges = edges_str.split(component_separator)
        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        curve = curve_str
        keep_ratio_mode = cmds.checkBox(
            self.cb_keep_ratio_mode, q=True, v=True)

        n = int(cmds.textField(self.tx_rebuild_resolution, q=True, tx=True))
        alignEdgesOnCurve(edges, curve_str, keep_ratio_mode)


    def onFitSelection(self, *args):
        """ 選択カーブのみ fit to curve """
        select_objects = [nu.get_object(x) for x in cmds.ls(selection=True)]
        curves = [x for x in select_objects if isValid(x)]

        for curve in curves:
            curve_str = curve
            if isValid(curve_str) and isAvailable(curve_str):
                attr_fullname = curve_str + "." + attr_name
                edges_str = cmds.getAttr(attr_fullname)
                edges = edges_str.split(component_separator)
                keep_ratio_mode = cmds.checkBox(self.cb_keep_ratio_mode, q=True, v=True)
                alignEdgesOnCurve(edges, curve_str, keep_ratio_mode)

        cmds.select(select_objects)

    def onFitAll(self, *args):
        """ 全カーブfit to curve """

        all_curves = getAllCurves()
        for curve in all_curves:
            curve_str = curve
            if isValid(curve_str) and isAvailable(curve_str):
                attr_fullname = curve_str + "." + attr_name
                edges_str = cmds.getAttr(attr_fullname)
                edges = edges_str.split(component_separator)
                keep_ratio_mode = cmds.checkBox(self.cb_keep_ratio_mode, q=True, v=True)
                alignEdgesOnCurve(edges, curve_str, keep_ratio_mode)


    def onReMakeCurve(self, *args):
        """
        アクティブエッジでアクティブカーブを作り直す
        """
        edges_str = cmds.textField(self.ed_edges, q=True, tx=True)
        edges = edges_str.split(component_separator)

        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        curve = curve_str

        # 既存カーブの削除
        cmds.delete(curve)

        cmds.select(edges)
        new_curve = cmds.polyToCurve(
            form=2, degree=3, conformToSmoothMeshPreview=1)[0]
        cmds.rebuildCurve(new_curve, ch=1, rpo=1, rt=0, end=1,
                          kr=0, kcp=0, kep=1, kt=0, s=5, d=3, tol=0.01)
        # カーブのヒストリ消す
        cmds.DeleteHistory(new_curve)

        #リネーム
        cmds.rename(new_curve, curve)

        cmds.textField(self.ed_curve, e=True, tx=curve)

        # カーブオブジェクトにアトリビュート追加
        addAttributes(curve_str, edges_str)

    def onReAssignEdges(self, *args):
        """
        カーブの形状からエッジ列を再設定
        """
        nu.message("not implemented")
        pass

    def onRebuildResolutionDiv2(self, *args):
        n = int(cmds.textField(self.tx_rebuild_resolution, q=True, tx=True))
        cmds.textField(self.tx_rebuild_resolution, e=True, tx=n//2)

    def onRebuildResolutionMul2(self, *args):
        n = int(cmds.textField(self.tx_rebuild_resolution, q=True, tx=True))
        cmds.textField(self.tx_rebuild_resolution, e=True, tx=n*2)

        if n <= 0:
            cmds.textField(self.tx_rebuild_resolution, e=True, tx=1)

    def rebuild_with_setting(self, curve_str, n):
        if n <= 0:
            cmds.rebuildCurve(curve_str, ch=1, rpo=1, rt=0, end=1, kr=2, kcp=0, kep=1, kt=0, s=1, d=1, tol=0.01)
        else:
            cmds.rebuildCurve(curve_str, ch=1, rpo=1, rt=0, end=1, kr=0, kcp=0, kep=1, kt=0, s=n, d=3, tol=0.01)

    def onRebuildActive(self, *args):
        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        n = int(cmds.textField(self.tx_rebuild_resolution, q=True, tx=True))
        self.rebuild_with_setting(curve_str, n)
        cmds.select(curve_str)
        cmds.selectMode(component=True)
        cmds.selectType(cv=True)

    def onRebuildSelection(self, *args):
        curves = [x for x in cmds.ls(selection=True) if isValid(x)]
        n = int(cmds.textField(self.tx_rebuild_resolution, q=True, tx=True))

        for curve_str in curves:
            self.rebuild_with_setting(curve_str, n)

        cmds.select(curves)
        cmds.selectMode(component=True)
        cmds.selectType(cv=True)

    def onRebuildAll(self, *args):
        curves = getAllCurves()
        n = int(cmds.textField(self.tx_rebuild_resolution, q=True, tx=True))

        for curve_str in curves:
            self.rebuild_with_setting(curve_str, n)

        cmds.select(curves)
        cmds.selectMode(component=True)
        cmds.selectType(cv=True)

    def onRebuildOp(self, *args):
        cmds.RebuildCurveOptions()

    def smooth_with_setting(self, curve_str):
        target_str = curve_str + ".cv[*]"
        cmds.smoothCurve(target_str, ch=1, rpo=1, s=1)

    def onSmoothActive(self, *args):
        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        self.smooth_with_setting(curve_str)

    def onSmoothSelection(self, *args):
        curves = [x for x in cmds.ls(selection=True) if isValid(x)]

        for curve_str in curves:
            self.smooth_with_setting(curve_str)

        cmds.select(curves)

    def onSmoothAll(self, *args):
        curves = getAllCurves()

        for curve_str in curves:
            self.smooth_with_setting(curve_str)

    def onSmoothOp(self, *args):
        cmds.SmoothCurveOptions()


    def onSelectAll(self, *args):
        """
        すべてのカーブを選択する
        """
        all_curves = getAllCurves()
        cmds.select(all_curves)

    def onSelectActive(self, *args):
        """
        アクティブなカーブを選択する
        """
        curve_str = cmds.textField(self.ed_curve, q=True, tx=True)
        cmds.select(curve_str)

    def onSelectVisible(self, *args):
        """
        表示されているカーブのみ選択する
        """
        all_curves = getAllCurves()
        visible_curves = [c for c in all_curves if cmds.getAttr(c+".visibility")]
        cmds.select(visible_curves)

    def onSelectInvisible(self, *args):
        """
        非表示のカーブのみ選択する
        """
        all_curves = getAllCurves()
        invisible_curves = [c for c in all_curves if not cmds.getAttr(c+".visibility")]
        cmds.select(invisible_curves)

    def onEnableDrawOnTop(self, *args):
        selections = nu.get_selection()

        for obj in selections:
            if isValid(obj):
                shape = cmds.listRelatives(obj, shapes=True)[0]
                cmds.setAttr(shape + ".alwaysDrawOnTop", 1)

    def onDisableDrawOnTop(self, *args):
        selections = nu.get_selection()

        for obj in selections:
            if isValid(obj):
                shape = cmds.listRelatives(obj, shapes=True)[0]
                cmds.setAttr(shape + ".alwaysDrawOnTop", 0)


def showNNToolWindow():
    NN_ToolWindow().create()

def main():
    showNNToolWindow()

if __name__ == "__main__":
    main()