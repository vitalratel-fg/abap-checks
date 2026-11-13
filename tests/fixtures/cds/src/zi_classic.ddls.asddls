@AbapCatalog.sqlViewName: 'ZICLS'
@AccessControl.authorizationCheck: #CHECK
define view zi_classic as select distinct from zt_one as o { key o.k as K }
