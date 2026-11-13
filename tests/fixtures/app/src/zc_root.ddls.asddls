define view entity ZC_ROOT as select from zt as r
  association of one to many ZC_ITEM as _Items on _Items.K = r.k
{ key r.k as K, _Items }
